"""The job that copies accepted cards into the knowledge base."""

import pytest
from langchain_core.stores import InMemoryByteStore
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.ai.knowledge.indexing import create_record_manager
from app.core.settings import Settings
from app.jobs import card_embedding
from app.jobs.card_embedding import embed_cards
from app.jobs.execution import JobContext
from app.models import AiUsage, Card, Deck, KnowledgeChunk, User
from app.repositories.users import UserRepository
from app.services.budget import MATERIALS, BudgetService

pytestmark = pytest.mark.usefixtures("trust_everyone")


@pytest.fixture
def settings(engine):
    return Settings(
        database_url=engine.url.render_as_string(hide_password=False),
        ai_embedder_provider="fake",
    )


@pytest.fixture
async def factory(engine):
    """Real commits, since the vector store uses its own connections."""
    await create_record_manager(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    async with engine.begin() as connection:
        await connection.execute(text("DELETE FROM knowledge_chunks"))
        await connection.execute(delete(User).where(User.email == "cards@example.com"))
        await connection.execute(text("DELETE FROM upsertion_record"))


@pytest.fixture
async def user_and_deck(factory):
    async with factory() as session:
        user = User(email="cards@example.com", password_hash="not-a-real-hash")
        session.add(user)
        await session.flush()
        deck = Deck(user_id=user.id, name="Biology")
        session.add(deck)
        await session.commit()
    return user, deck


@pytest.fixture
def make_cards(factory, user_and_deck):
    async def _make_cards(*fronts) -> list[Card]:
        cards = [Card(deck_id=user_and_deck[1].id, front=front, back="A") for front in fronts]
        async with factory() as session:
            session.add_all(cards)
            await session.commit()
        return cards

    return _make_cards


@pytest.fixture
def run(factory, engine, settings, user_and_deck):
    async def _run(card_ids, user_id=None, **options) -> dict:
        async def report(_):
            pass

        payload = {"card_ids": card_ids, **options}
        context = JobContext(1, user_id or user_and_deck[0].id, payload, factory, report)
        return await embed_cards(context, engine, settings, InMemoryByteStore())

    return _run


async def _saved(factory) -> list[tuple[str, int | None, int | None]]:
    async with factory() as session:
        rows = await session.execute(
            select(KnowledgeChunk.content, KnowledgeChunk.source_card_id, KnowledgeChunk.owner_id)
        )
        return [tuple(row) for row in rows]


async def test_accepted_cards_join_the_knowledge_base(factory, make_cards, run):
    [first, second] = await make_cards("What divides?", "What flows?")

    result = await run([first.id, second.id])

    assert result == {"saved": 2}
    assert sorted(await _saved(factory)) == [
        ("What divides? A", first.id, None),
        ("What flows? A", second.id, None),
    ]


async def test_a_private_card_gets_a_vector_but_stays_out_of_the_knowledge_base(
    factory, make_cards, run
):
    [card] = await make_cards("What divides?")

    assert await run([card.id], share=False) == {"saved": 0}

    assert await _saved(factory) == []
    async with factory() as session:
        model, vector = (
            await session.execute(
                select(Card.embedding_model, Card.embedding).where(Card.id == card.id)
            )
        ).one()
    assert model == "fake"
    assert vector is not None


async def test_the_same_fact_twice_in_a_batch_is_saved_once(factory, make_cards, run):
    cards = await make_cards("What divides?", "What divides?")

    assert await run([card.id for card in cards]) == {"saved": 1}


async def test_a_fact_already_known_isnt_saved_again(factory, make_cards, run):
    [first] = await make_cards("What divides?")
    await run([first.id])
    [repeat] = await make_cards("What divides?")

    assert await run([repeat.id]) == {"saved": 0}
    assert len(await _saved(factory)) == 1


async def _shared_count(factory) -> int:
    async with factory() as session:
        return await session.scalar(
            select(func.count()).select_from(KnowledgeChunk).where(KnowledgeChunk.shared.is_(True))
        )


async def test_a_card_is_shared_only_after_a_second_learner_accepts_it(factory, make_cards, run):
    [first] = await make_cards("What divides?")
    await run([first.id])
    assert await _shared_count(factory) == 0

    # The same learner accepting it again doesn't count.
    [again] = await make_cards("What divides?")
    await run([again.id])
    assert await _shared_count(factory) == 0

    async with factory() as session:
        second = User(email="second@embedding.test", password_hash="not-a-real-hash")
        session.add(second)
        await session.commit()
    try:
        [theirs] = await make_cards("What divides?")
        await run([theirs.id], user_id=second.id)
        assert await _shared_count(factory) == 1
        assert len(await _saved(factory)) == 1
    finally:
        async with factory() as session:
            await session.execute(delete(User).where(User.id == second.id))
            await session.commit()


@pytest.fixture
async def second_learner(factory):
    async with factory() as session:
        second = User(email="second@embedding.test", password_hash="not-a-real-hash")
        session.add(second)
        await session.commit()
    yield second
    async with factory() as session:
        await session.execute(delete(User).where(User.id == second.id))
        await session.commit()


def _trust_only(monkeypatch, *user_ids):
    async def trusted(_repository, user_id):
        return user_id in user_ids

    monkeypatch.setattr(UserRepository, "is_trusted", trusted)


async def test_a_new_account_cant_confirm_a_card(
    factory, make_cards, run, second_learner, user_and_deck, monkeypatch
):
    _trust_only(monkeypatch, user_and_deck[0].id)
    [first] = await make_cards("What divides?")
    await run([first.id])

    [theirs] = await make_cards("What divides?")
    await run([theirs.id], user_id=second_learner.id)

    assert await _shared_count(factory) == 0


async def test_a_trusted_learner_takes_over_from_a_new_account(
    factory, make_cards, run, second_learner, monkeypatch
):
    _trust_only(monkeypatch, second_learner.id)
    [first] = await make_cards("What divides?")
    await run([first.id])

    [theirs] = await make_cards("What divides?")
    await run([theirs.id], user_id=second_learner.id)

    assert await _shared_count(factory) == 0
    async with factory() as session:
        accepted_by = await session.scalar(select(KnowledgeChunk.accepted_by))
    assert accepted_by == second_learner.id


async def test_a_retry_adds_nothing(factory, make_cards, run):
    [card] = await make_cards("What divides?")

    await run([card.id])
    await run([card.id])

    assert len(await _saved(factory)) == 1


async def test_deleted_cards_are_skipped(factory, run):
    assert await run([0]) == {"saved": 0}
    assert await _saved(factory) == []


async def test_a_full_budget_skips_the_work(factory, make_cards, run, monkeypatch):
    async def full(*_, **__):
        return False

    monkeypatch.setattr(BudgetService, "within_model_limits", full)
    [card] = await make_cards("What divides?")

    assert await run([card.id]) == {"saved": 0}
    assert await _saved(factory) == []


async def test_what_it_spent_is_recorded(factory, make_cards, run):
    [card] = await make_cards("What divides?")

    await run([card.id])

    async with factory() as session:
        feature = await session.scalar(select(AiUsage.feature))
        total = await session.scalar(select(func.sum(AiUsage.calls)))
    assert feature == MATERIALS
    assert total == 1


def test_similarity_compares_direction():
    def similarity(first, second):
        return card_embedding._dot(card_embedding._unit(first), card_embedding._unit(second))

    assert similarity([2.0, 0.0], [3.0, 0.0]) == pytest.approx(1.0)
    assert similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert similarity([0.0, 0.0], [1.0, 0.0]) == 0.0
