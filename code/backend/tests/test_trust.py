"""When an account's uploads can reach other learners."""

import uuid
from datetime import timedelta

import pytest

from app.core.settings import EMBEDDING_DIMENSIONS
from app.models import Card, ChunkReport, Deck, KnowledgeChunk, User, utcnow
from app.repositories.knowledge import KnowledgeRepository
from app.repositories.users import (
    FINISHED_DECK_CARDS,
    FINISHED_DECK_INTERVAL_DAYS,
    UserRepository,
)
from app.scheduler import CardState
from app.services.trust import (
    TRUST_ACCOUNT_AGE,
    TRUST_FINISHED_DECKS,
    TRUST_LOSS_REPORTERS,
    TRUST_LOSS_WINDOW,
    grant_if_earned,
    revoke_if_reported,
)

DAY = timedelta(days=1)


@pytest.fixture
def age(session):
    async def _age(user: User, older_than_needed=True) -> None:
        user.created_at = utcnow() - TRUST_ACCOUNT_AGE + (-DAY if older_than_needed else DAY)
        await session.commit()

    return _age


@pytest.fixture
def finish(make_deck, make_card):
    """Decks whose cards all graduated, last reviewed `reviewed_ago`."""

    async def _finish(
        user: User,
        decks=TRUST_FINISHED_DECKS,
        reviewed_ago=DAY,
        cards=FINISHED_DECK_CARDS,
        interval_days=FINISHED_DECK_INTERVAL_DAYS,
    ) -> list[Deck]:
        made = []
        for _ in range(decks):
            deck = await make_deck(user, name="Studied")
            for _ in range(cards):
                await make_card(
                    deck,
                    state=CardState.REVIEW.value,
                    interval_days=interval_days,
                    last_reviewed_at=utcnow() - reviewed_ago,
                )
            made.append(deck)
        return made

    return _finish


@pytest.fixture
def earn(session):
    """Runs the check a review makes after a card in `deck` reaches review."""

    async def _earn(user: User, deck: Deck) -> bool:
        users = UserRepository(session)
        await grant_if_earned(user, deck.id, utcnow(), users, KnowledgeRepository(session))
        await session.commit()
        return await users.is_trusted(user.id)

    return _earn


@pytest.fixture
def waiting_chunk(session):
    async def _waiting_chunk(owner: User, **fields) -> KnowledgeChunk:
        chunk = KnowledgeChunk(
            langchain_id=uuid.uuid4(),
            content="A passage",
            embedding=[1.0, *[0.0] * (EMBEDDING_DIMENSIONS - 1)],
            embedding_model="m",
            owner_id=owner.id,
            passed_screening=True,
            **fields,
        )
        session.add(chunk)
        await session.commit()
        return chunk

    return _waiting_chunk


@pytest.fixture
def reported(session, make_user, waiting_chunk):
    """Reports from different learners against one of `target`'s chunks."""

    async def _reported(target: User, reporters: int, trusted=True, ago=DAY) -> None:
        chunk = await waiting_chunk(target)
        for i in range(reporters):
            reporter = await make_user(f"reporter{i}@example.com")
            session.add(
                ChunkReport(
                    reporter_id=reporter.id,
                    target_user_id=target.id,
                    chunk_id=chunk.langchain_id,
                    reporter_trusted=trusted,
                    created_at=utcnow() - ago,
                )
            )
        await session.commit()

    return _reported


@pytest.fixture
def revoke(session):
    async def _revoke(user: User) -> bool:
        """Whether `user` is still trusted afterwards."""
        users = UserRepository(session)
        await revoke_if_reported(user.id, utcnow(), users, KnowledgeRepository(session))
        await session.commit()
        return await users.is_trusted(user.id)

    return _revoke


async def test_enough_finished_decks_earn_trust(me, age, finish, earn):
    await age(me)
    decks = await finish(me)

    assert await earn(me, decks[0]) is True


async def test_a_new_account_isnt_trusted_however_much_it_studies(me, age, finish, earn):
    await age(me, older_than_needed=False)
    decks = await finish(me)

    assert await earn(me, decks[0]) is False


async def test_too_few_finished_decks_dont_earn_trust(me, age, finish, earn):
    await age(me)
    decks = await finish(me, decks=TRUST_FINISHED_DECKS - 1)

    assert await earn(me, decks[0]) is False


@pytest.mark.parametrize(
    "unfinished",
    [
        {"cards": FINISHED_DECK_CARDS - 1},
        {"interval_days": FINISHED_DECK_INTERVAL_DAYS - 1},
    ],
    ids=["too small", "learned in one sitting"],
)
async def test_only_real_decks_count_as_finished(me, age, finish, earn, unfinished):
    await age(me)
    decks = await finish(me, **unfinished)

    assert await earn(me, decks[0]) is False


async def test_a_deck_with_a_card_still_to_learn_isnt_finished(me, age, finish, earn, make_card):
    await age(me)
    decks = await finish(me)
    await make_card(decks[0], state=CardState.LEARNING.value)

    assert await earn(me, decks[0]) is False


async def test_a_missing_account_isnt_trusted(session):
    assert await UserRepository(session).is_trusted(-1) is False


async def test_a_review_that_finishes_the_last_deck_earns_trust_and_shares(
    client, session, me, age, finish, make_card, waiting_chunk
):
    chunk = await waiting_chunk(me)
    hidden = await waiting_chunk(me, hidden=True)
    await age(me)
    decks = await finish(me)
    due = await make_card(
        decks[0],
        state=CardState.REVIEW.value,
        interval_days=FINISHED_DECK_INTERVAL_DAYS,
        due_at=utcnow() - DAY,
        last_reviewed_at=utcnow() - DAY * FINISHED_DECK_INTERVAL_DAYS,
    )

    response = await client.post(f"/api/cards/{due.id}/review", json={"rating": "good"})

    assert response.status_code == 200
    session.expunge_all()
    assert (await session.get(User, me.id)).trusted_at is not None
    assert (await session.get(KnowledgeChunk, chunk.langchain_id)).shared is True
    assert (await session.get(KnowledgeChunk, hidden.langchain_id)).shared is not True
    assert (await session.get(Card, due.id)).last_reviewed_at >= utcnow() - DAY


async def test_a_review_leaves_chunks_waiting_until_then(
    client, session, me, waiting_chunk, make_deck, make_card
):
    chunk = await waiting_chunk(me)
    card = await make_card(await make_deck(me))

    await client.post(f"/api/cards/{card.id}/review", json={"rating": "good"})

    session.expunge_all()
    assert (await session.get(KnowledgeChunk, chunk.langchain_id)).shared is not True


@pytest.mark.parametrize(
    ("reporters", "reporters_trusted", "ago", "still_trusted"),
    [
        (TRUST_LOSS_REPORTERS, True, DAY, False),
        (TRUST_LOSS_REPORTERS - 1, True, DAY, True),
        (TRUST_LOSS_REPORTERS, False, DAY, True),
        (TRUST_LOSS_REPORTERS, True, TRUST_LOSS_WINDOW + DAY, True),
    ],
    ids=["enough", "too few", "untrusted reporters", "too old"],
)
async def test_reports_from_trusted_learners_take_trust_away(
    session, me, reported, revoke, reporters, reporters_trusted, ago, still_trusted
):
    me.trusted_at = utcnow() - TRUST_LOSS_WINDOW * 2
    await session.commit()
    await reported(me, reporters, reporters_trusted, ago)

    assert await revoke(me) is still_trusted


async def test_reports_from_before_trust_was_earned_dont_count(session, me, reported, revoke):
    await reported(me, TRUST_LOSS_REPORTERS, ago=DAY * 2)
    me.trusted_at = utcnow() - DAY
    await session.commit()

    assert await revoke(me) is True


@pytest.mark.parametrize(
    ("lost_ago", "reviewed_ago", "earned"),
    [
        (TRUST_LOSS_WINDOW + DAY * 2, DAY, True),
        (TRUST_LOSS_WINDOW + DAY * 2, TRUST_LOSS_WINDOW + DAY * 3, False),
        (TRUST_LOSS_WINDOW - DAY, DAY, False),
    ],
    ids=["studied since", "only studied before", "too soon"],
)
async def test_lost_trust_needs_new_study_to_come_back(
    session, me, age, finish, earn, lost_ago, reviewed_ago, earned
):
    await age(me)
    me.trust_lost_at = utcnow() - lost_ago
    await session.commit()
    decks = await finish(me, reviewed_ago=reviewed_ago)

    assert await earn(me, decks[0]) is earned


async def test_restoring_trust_ignores_the_earlier_reports(session, me, reported, revoke):
    await reported(me, TRUST_LOSS_REPORTERS)
    me.trust_lost_at = utcnow()
    await session.commit()

    assert await UserRepository(session).restore_trust(me.id, utcnow()) is True
    await session.commit()

    assert await revoke(me) is True
