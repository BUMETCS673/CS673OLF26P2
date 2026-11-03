"""Starting problem card reviews, the job that runs them, and applying decisions."""

from datetime import timedelta

import pytest
from ai_fakes import ScriptedModel
from sqlalchemy import func, select

from app.ai.checkpoints import discard_threads, open_checkpointer
from app.ai.judge import PASSED
from app.ai.problem_cards.context import ProblemCardContext
from app.ai.problem_cards.graph import ReviewOutcome, resume_review, start_review
from app.ai.schemas import CardDraft, CardFixes, Diagnosis, FixOption, Verdict, Verdicts
from app.core.errors import NotFound
from app.core.settings import Settings, get_settings
from app.jobs import problem_cards as job_module
from app.jobs.execution import JobContext
from app.jobs.problem_cards import MAX_CARDS_PER_REVIEW, review_problem_cards
from app.jobs.tasks import HANDLERS
from app.models import AiUsage, Card, Job, ProblemCardReview, utcnow
from app.models.job import EMBED_CARDS, REVIEW_PROBLEM_CARDS
from app.models.job import FAILED as JOB_FAILED
from app.models.problem_card_review import COMPLETED, FAILED, PENDING, QUEUED
from app.scheduler import CardState
from app.services import problem_cards as service_module
from app.services.budget import PROBLEM_CARDS, BudgetService


@pytest.fixture
async def deck(make_deck, me):
    return await make_deck(me)


async def _count(session, model) -> int:
    return await session.scalar(select(func.count()).select_from(model))


# --- starting -----------------------------------------------------------------------------


@pytest.fixture
def answer(client):
    """Forgets a card in review, which adds a lapse."""

    async def _answer(card, rating="again"):
        return await client.post(f"/api/cards/{card.id}/review", json={"rating": rating})

    return _answer


@pytest.fixture
def lapsing_card(make_card, deck):
    async def _lapsing_card(**fields) -> Card:
        values = {
            "state": CardState.REVIEW.value,
            "due_at": utcnow() - timedelta(days=1),
            "interval_days": 10,
            "lapses": 3,
            "problem_at_lapses": 4,
            **fields,
        }
        return await make_card(deck, **values)

    return _lapsing_card


async def test_crossing_the_limit_starts_a_delayed_review(
    session, me, deck, answer, lapsing_card
):
    response = await answer(await lapsing_card())

    assert response.status_code == 200
    review = await session.scalar(select(ProblemCardReview))
    assert (review.user_id, review.deck_id, review.status) == (me.id, deck.id, QUEUED)
    job = await session.get(Job, review.job_id)
    assert job.kind == REVIEW_PROBLEM_CARDS
    assert job.payload == {"review_id": review.id}
    assert job.retry_at > utcnow()


async def test_below_the_limit_starts_nothing(session, answer, lapsing_card):
    await answer(await lapsing_card(lapses=0))

    assert await _count(session, ProblemCardReview) == 0


async def test_a_deck_has_one_active_review(session, answer, lapsing_card):
    await answer(await lapsing_card(front="First?"))
    await answer(await lapsing_card(front="Second?"))

    assert await _count(session, ProblemCardReview) == 1
    assert await _count(session, Job) == 1


async def test_dismissing_a_whole_review_pauses_new_ones(session, me, deck, answer, lapsing_card):
    session.add(
        ProblemCardReview(
            user_id=me.id,
            deck_id=deck.id,
            thread_id="old",
            status=COMPLETED,
            completed_at=utcnow(),
            decisions=[{"card_id": 1, "kind": None, "new_card_ids": []}],
        )
    )
    await session.commit()

    await answer(await lapsing_card())

    assert await _count(session, ProblemCardReview) == 1


async def test_turning_it_off_starts_nothing(session, answer, lapsing_card, monkeypatch):
    monkeypatch.setattr(get_settings(), "ai_problem_cards_enabled", False)

    await answer(await lapsing_card())

    assert await _count(session, ProblemCardReview) == 0


# --- the job ------------------------------------------------------------------------------


@pytest.fixture
def settings(engine):
    return Settings(
        database_url=engine.url.render_as_string(hide_password=False),
        ai_writer_provider="fake",
        ai_judge_provider="fake",
    )


@pytest.fixture
def make_review(session, me, deck):
    async def _make_review(**fields) -> ProblemCardReview:
        values = {"user_id": me.id, "deck_id": deck.id, "thread_id": "thread", **fields}
        review = ProblemCardReview(**values)
        session.add(review)
        await session.commit()
        return review

    return _make_review


@pytest.fixture
def context_for(me, session_factory):
    def _context_for(review) -> JobContext:
        async def report(_):
            pass

        return JobContext(1, me.id, {"review_id": review.id}, session_factory, report)

    return _context_for


@pytest.fixture
def graph(monkeypatch):
    """Records each run instead of calling models, and answers with `graph.outcome`."""

    class _Graph:
        outcome = ReviewOutcome([], None, "passed")
        contexts = []

    _Graph.contexts = []

    async def run(context, _checkpointer, thread_id):
        _Graph.contexts.append((context, thread_id))
        return _Graph.outcome

    async def no_discard(*_):
        pass

    monkeypatch.setattr(job_module, "start_review", run)
    monkeypatch.setattr(job_module, "discard_threads", no_discard)
    return _Graph


def _recommendation(card, kinds=("rewrite",)) -> dict:
    return {
        "card_id": card.id,
        "front": card.front,
        "back": card.back,
        "lapses": card.lapses,
        "options": [
            {"kind": kind, "reason": "Why.", "cards": [{"front": f"New {kind}?", "back": "A"}]}
            for kind in kinds
        ],
    }


async def test_a_run_leaves_the_review_waiting_for_the_learner(
    session, make_review, make_card, deck, context_for, settings, graph
):
    card = await make_card(deck, lapses=6, problem_at_lapses=4)
    other = await make_card(deck, lapses=5, problem_at_lapses=4, front="Other?")
    review = await make_review()
    graph.outcome = ReviewOutcome([_recommendation(card)], "Same topic.", "passed")

    result = await review_problem_cards(context_for(review), settings)

    assert result == {"review_id": review.id, "recommended": 1}
    session.expunge_all()
    saved = await session.get(ProblemCardReview, review.id)
    assert (saved.status, saved.shared_cause, saved.verification) == (
        PENDING,
        "Same topic.",
        "passed",
    )
    assert saved.card_ids == [card.id, other.id]  # most lapses first
    assert (await session.get(Card, other.id)).problem_at_lapses == 7  # no fix, so it goes quiet
    assert (await session.get(Card, card.id)).problem_at_lapses == 4  # still waiting on a decision
    assert graph.contexts[0][1] == "thread"


async def test_a_run_only_sends_the_worst_cards(
    make_review, make_card, deck, context_for, settings, graph
):
    for number in range(MAX_CARDS_PER_REVIEW + 2):
        await make_card(deck, front=f"Q{number}?", lapses=4 + number, problem_at_lapses=4)

    await review_problem_cards(context_for(await make_review()), settings)

    context = graph.contexts[0][0]
    assert len(context.cards) == MAX_CARDS_PER_REVIEW
    assert context.cards[0]["lapses"] == 4 + MAX_CARDS_PER_REVIEW + 1


async def test_nothing_recommended_completes_the_review(
    session, make_review, make_card, deck, context_for, settings, graph
):
    await make_card(deck, lapses=4, problem_at_lapses=4)
    review = await make_review()

    await review_problem_cards(context_for(review), settings)

    session.expunge_all()
    saved = await session.get(ProblemCardReview, review.id)
    assert saved.status == COMPLETED
    assert saved.completed_at is not None


async def test_no_flagged_cards_completes_without_a_run(
    session, make_review, context_for, settings, graph
):
    review = await make_review()

    await review_problem_cards(context_for(review), settings)

    session.expunge_all()
    assert (await session.get(ProblemCardReview, review.id)).status == COMPLETED
    assert graph.contexts == []


async def test_no_budget_runs_the_review_again_later(
    session, make_review, make_card, deck, context_for, settings, graph, monkeypatch
):
    async def full(*_, **__):
        return False

    monkeypatch.setattr(BudgetService, "within_model_limits", full)
    card = await make_card(deck, lapses=4, problem_at_lapses=4)
    review = await make_review()

    await review_problem_cards(context_for(review), settings)

    session.expunge_all()
    assert graph.contexts == []
    saved = await session.get(ProblemCardReview, review.id)
    assert saved.status == QUEUED
    job = await session.get(Job, saved.job_id)
    assert job.kind == REVIEW_PROBLEM_CARDS
    assert job.payload == {"review_id": review.id}
    assert job.retry_at > utcnow()
    assert (await session.get(Card, card.id)).problem_at_lapses == 4


async def test_a_finished_review_isnt_run_again(make_review, context_for, settings, graph):
    review = await make_review(status=PENDING)

    assert await review_problem_cards(context_for(review), settings) is None
    assert graph.contexts == []


async def test_a_failed_run_records_its_spending_and_raises(
    session, make_review, make_card, deck, context_for, settings, monkeypatch
):
    await make_card(deck, lapses=4, problem_at_lapses=4)

    async def fail(context, _checkpointer, _thread):
        context.writer.callbacks[0].count_call()
        raise NotFound("boom")

    monkeypatch.setattr(job_module, "start_review", fail)

    with pytest.raises(NotFound):
        await review_problem_cards(context_for(await make_review()), settings)

    assert await session.scalar(select(AiUsage.feature)) == PROBLEM_CARDS


def test_the_job_is_registered():
    assert REVIEW_PROBLEM_CARDS in HANDLERS


# --- reading ------------------------------------------------------------------------------


@pytest.fixture
def no_checkpointer(monkeypatch):
    """Records what would resume the run, without a real checkpointer."""
    calls = []

    class _Saver:
        async def __aenter__(self):
            return "saver"

        async def __aexit__(self, *_):
            return False

    async def resume(_saver, thread_id, decisions):
        calls.append(("resume", thread_id, decisions))

    async def discard(_url, thread_ids):
        calls.append(("discard", list(thread_ids)))

    monkeypatch.setattr(service_module, "open_checkpointer", lambda _url: _Saver())
    monkeypatch.setattr(service_module, "resume_review", resume)
    monkeypatch.setattr(service_module, "discard_threads", discard)
    return calls


async def test_the_summary_lists_whats_ready_and_whats_coming(
    client, deck, make_review, make_card, no_checkpointer
):
    card = await make_card(deck)
    review = await make_review(status=PENDING, recommendations=[_recommendation(card)])

    response = await client.get("/api/problem-cards")

    assert response.json() == {
        "processing": False,
        "ready": [
            {
                "review_id": review.id,
                "deck_id": deck.id,
                "deck_name": deck.name,
                "card_count": 1,
            }
        ],
    }


async def test_a_queued_review_counts_as_processing(client, make_review):
    await make_review()

    assert (await client.get("/api/problem-cards")).json()["processing"] is True


async def test_a_job_out_of_attempts_fails_its_review(
    client, session, me, deck, make_card, make_review, no_checkpointer
):
    card = await make_card(deck, lapses=4, problem_at_lapses=4)
    job = Job(user_id=me.id, kind=REVIEW_PROBLEM_CARDS, status=JOB_FAILED)
    session.add(job)
    await session.commit()
    review = await make_review(job_id=job.id, card_ids=[card.id])

    body = (await client.get("/api/problem-cards")).json()

    assert body["processing"] is False
    session.expunge_all()
    assert (await session.get(ProblemCardReview, review.id)).status == FAILED
    assert (await session.get(Card, card.id)).problem_at_lapses == 6
    assert no_checkpointer == [("discard", ["thread"])]


async def test_a_deck_shows_its_waiting_review(client, deck, make_card, make_review):
    assert (await client.get(f"/api/decks/{deck.id}/problem-card-review")).json() == {
        "review": None
    }
    card = await make_card(deck)
    review = await make_review(status=PENDING, recommendations=[_recommendation(card)])

    body = (await client.get(f"/api/decks/{deck.id}/problem-card-review")).json()

    assert body["review"]["id"] == review.id
    assert body["review"]["recommendations"][0]["card_id"] == card.id


async def test_someone_elses_deck_has_no_review(client, me, make_deck, make_user):
    other = await make_user(email="other@example.com")
    deck = await make_deck(other)

    assert (await client.get(f"/api/decks/{deck.id}/problem-card-review")).status_code == 404


# --- deciding -----------------------------------------------------------------------------


@pytest.fixture
def pending(make_review, make_card, deck):
    async def _pending(*kinds) -> tuple[ProblemCardReview, Card]:
        card = await make_card(deck, lapses=4, problem_at_lapses=4)
        kinds = kinds or ("rewrite", "contrast")
        recommendations = [_recommendation(card, kinds)]
        return await make_review(status=PENDING, recommendations=recommendations), card

    return _pending


async def _decide(client, review, *decisions):
    return await client.post(
        f"/api/problem-card-reviews/{review.id}/decisions", json={"decisions": list(decisions)}
    )


async def test_a_replacing_fix_swaps_the_card(client, session, pending, no_checkpointer):
    review, card = await pending()

    response = await _decide(client, review, {"card_id": card.id, "option": 0})

    assert response.status_code == 200
    body = response.json()
    assert body["review"]["status"] == COMPLETED
    assert body["review"]["decisions"][0]["kind"] == "rewrite"
    assert [new["front"] for new in body["cards"]] == ["New rewrite?"]
    assert body["cards"][0]["origin"] == "ai"
    session.expunge_all()
    assert await session.get(Card, card.id) is None
    job = await session.scalar(select(Job).where(Job.kind == EMBED_CARDS))
    assert job.payload == {"card_ids": [body["cards"][0]["id"]]}
    assert no_checkpointer == [
        ("resume", "thread", [{"card_id": card.id, "option": 0}]),
        ("discard", ["thread"]),
    ]


async def test_an_adding_fix_keeps_the_card_and_quiets_it(
    client, session, pending, no_checkpointer
):
    review, card = await pending()

    await _decide(client, review, {"card_id": card.id, "option": 1})

    session.expunge_all()
    saved = await session.get(Card, card.id)
    assert saved.problem_at_lapses == 6
    assert await _count(session, Card) == 2


async def test_removing_deletes_the_card(client, session, pending, no_checkpointer):
    review, card = await pending()

    response = await _decide(client, review, {"card_id": card.id, "option": "remove"})

    assert response.json()["review"]["decisions"][0]["kind"] == "remove"
    assert await _count(session, Card) == 0


async def test_keeping_quiets_the_card_and_creates_nothing(
    client, session, pending, no_checkpointer
):
    review, card = await pending()

    response = await _decide(client, review, {"card_id": card.id, "option": None})

    assert response.json()["cards"] == []
    session.expunge_all()
    assert (await session.get(Card, card.id)).problem_at_lapses == 6
    assert await _count(session, Job) == 0


async def test_a_card_deleted_meanwhile_is_skipped(client, session, pending, no_checkpointer):
    review, card = await pending()
    await session.delete(card)
    await session.commit()

    response = await _decide(client, review, {"card_id": card.id, "option": 0})

    assert response.status_code == 200
    assert response.json()["cards"] == []


async def test_a_second_submission_conflicts(client, pending, no_checkpointer):
    review, card = await pending()
    await _decide(client, review, {"card_id": card.id, "option": None})

    response = await _decide(client, review, {"card_id": card.id, "option": None})

    assert response.status_code == 409


async def test_a_problem_finishing_the_run_doesnt_undo_the_decision(
    client, session, pending, no_checkpointer, monkeypatch
):
    async def fail(*_):
        raise RuntimeError

    monkeypatch.setattr(service_module, "resume_review", fail)
    review, card = await pending()

    response = await _decide(client, review, {"card_id": card.id, "option": None})

    assert response.status_code == 200
    assert no_checkpointer == [("discard", ["thread"])]


@pytest.mark.parametrize(
    "decision",
    [
        lambda card: {"card_id": card.id + 1, "option": 0},
        lambda card: {"card_id": card.id, "option": 9},
        lambda card: {"card_id": card.id, "option": -1},
        lambda card: {"card_id": card.id, "option": "delete"},
        lambda card: {"card_id": card.id, "option": True},
        lambda card: {"card_id": True, "option": 0},
        lambda _: "nope",
    ],
)
async def test_bad_decisions_are_refused(client, session, pending, no_checkpointer, decision):
    review, card = await pending()

    response = await _decide(client, review, decision(card))

    assert response.status_code == 422
    assert response.json()["error"]["field"] == "decisions"
    assert no_checkpointer == []


async def test_every_recommended_card_needs_a_decision(client, pending, no_checkpointer):
    review, card = await pending()

    assert (await _decide(client, review)).status_code == 422
    assert (
        await _decide(
            client,
            review,
            {"card_id": card.id, "option": 0},
            {"card_id": card.id, "option": 0},
        )
    ).status_code == 422


async def test_someone_elses_review_doesnt_exist(
    client, pending, make_user, login_as, no_checkpointer
):
    review, card = await pending()
    await login_as(await make_user(email="other@example.com"))

    response = await _decide(client, review, {"card_id": card.id, "option": 0})

    assert response.status_code == 404


# --- the real checkpointer ----------------------------------------------------------------


async def test_a_paused_run_survives_in_postgres_and_can_be_discarded(engine):
    url = engine.url.render_as_string(hide_password=False)
    option = FixOption(kind="rewrite", reason="Why.", cards=[CardDraft(front="New?", back="A")])
    context = ProblemCardContext(
        writer=ScriptedModel(Diagnosis(recommendations=[CardFixes(index=0, options=[option])])),
        judge=ScriptedModel(Verdicts(verdicts=[Verdict(index=0, ok=True)])),
        cards=[{"id": 1, "front": "Old?", "back": "B", "lapses": 4, "similar": []}],
        existing_fronts=[],
    )
    config = {"configurable": {"thread_id": "postgres-test"}}

    async with open_checkpointer(url) as saver:
        outcome = await start_review(context, saver, "postgres-test")
        assert outcome.verification == PASSED
        assert await saver.aget_tuple(config) is not None

    # A new checkpointer, as a later request would have.
    async with open_checkpointer(url) as saver:
        decisions = [{"card_id": 1, "option": 0}]
        assert await resume_review(saver, "postgres-test", decisions) == decisions

    await discard_threads(url, ["postgres-test"])
    async with open_checkpointer(url) as saver:
        assert await saver.aget_tuple(config) is None
