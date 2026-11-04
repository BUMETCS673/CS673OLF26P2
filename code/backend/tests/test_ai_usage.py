"""Counting what a run spends, budgets, and saving usage."""

from datetime import timedelta

import httpx
import pytest
from langchain_core.outputs import ChatResult
from langchain_google_genai.chat_models import GoogleAPIError
from sqlalchemy import select

from app.ai.failures import FALL_BACK_ON
from app.ai.fake import FakeChatModel, FakeEmbeddings
from app.ai.models import (
    GuardedEmbeddings,
    ModelSpec,
    Role,
    first_models,
    load_chat_model,
    load_embeddings,
    model_name,
)
from app.ai.schemas import CardBatch
from app.ai.usage import RunUsage
from app.core.settings import Settings
from app.models import AiUsage, utcnow
from app.repositories.usage import UsageRepository
from app.services.budget import GENERATE, PROBLEM_CARDS, SITE, USER, BudgetService


def _fake_settings(**values) -> Settings:
    return Settings(
        ai_writer_provider="fake",
        ai_judge_provider="fake",
        ai_embedder_provider="fake",
        **values,
    )


def _spent(user, calls, model="fake", feature=GENERATE, hours_ago=0) -> AiUsage:
    return AiUsage(
        feature=feature,
        role="writer",
        model=model,
        user_id=user.id,
        calls=calls,
        input_tokens=0,
        output_tokens=0,
        created_at=utcnow() - timedelta(hours=hours_ago),
    )


@pytest.fixture
def budget(session):
    def _budget(**values) -> BudgetService:
        return BudgetService(UsageRepository(session), _fake_settings(**values))

    return _budget


# --- counting -----------------------------------------------------------------------------


async def test_a_call_counts_its_tokens_under_its_role():
    run = RunUsage()

    await load_chat_model(Role.WRITER, _fake_settings(), run).ainvoke("Hello")

    [usage] = run.roles
    assert (usage.role, usage.model, usage.calls) == ("writer", "fake", 1)
    assert (usage.input_tokens, usage.output_tokens) == (10, 5)


async def test_structured_output_is_counted_too():
    run = RunUsage()
    model = load_chat_model(Role.WRITER, _fake_settings(), run)

    await model.with_structured_output(CardBatch).ainvoke("Write cards")

    assert run.roles[0].calls == 1


async def test_each_role_is_counted_separately():
    run = RunUsage()
    settings = _fake_settings()

    models = first_models(settings, [Role.WRITER, Role.JUDGE], judged=Role.WRITER)

    await load_chat_model(Role.WRITER, settings, run).ainvoke("Hello")
    await load_chat_model(Role.JUDGE, settings, run, models=models).ainvoke("Hello")
    await load_chat_model(Role.JUDGE, settings, run, models=models).ainvoke("Hello")

    assert {usage.role: usage.calls for usage in run.roles} == {"writer": 1, "judge": 2}


class OverloadedModel(FakeChatModel):
    def _generate(self, *_, **__):
        raise GoogleAPIError(503, {"error": {"code": 503, "message": "busy", "status": "X"}})


async def test_a_fallback_charges_only_the_model_that_answered():
    run = RunUsage()
    first = OverloadedModel(callbacks=[run.for_role(Role.JUDGE, "first")])
    later = FakeChatModel(callbacks=[run.for_role(Role.JUDGE, "later")])

    await first.with_fallbacks([later], exceptions_to_handle=FALL_BACK_ON).ainvoke("Hello")

    assert [(usage.model, usage.calls) for usage in run.roles] == [("later", 1)]


class FailingEmbeddings(FakeEmbeddings):
    def __init__(self, error):
        super().__init__()
        self.error = error

    async def aembed_query(self, text):
        raise self.error


@pytest.mark.parametrize(
    ("error", "spent"),
    [
        (GoogleAPIError(503, {"error": {"code": 503, "message": "busy", "status": "X"}}), 0),
        (httpx.ReadTimeout("slow"), 1),
    ],
)
async def test_an_embedding_call_is_refunded_only_when_refused(error, spent):
    run = RunUsage()
    embeddings = GuardedEmbeddings(FailingEmbeddings(error), None, run.for_role("embedder", "e"))

    with pytest.raises(type(error)):
        await embeddings.aembed_query("ATP")

    assert run.for_role("embedder", "e").calls == spent


async def test_a_failed_call_still_counts():
    class Failing(FakeChatModel):
        def _generate(self, *_, **__) -> ChatResult:
            raise ValueError("no reply")

    run = RunUsage()
    model = Failing(callbacks=[run.for_role(Role.WRITER, "fake")])

    with pytest.raises(ValueError):
        await model.ainvoke("Hello")

    assert run.roles[0].calls == 1


async def test_embedding_calls_are_counted():
    run = RunUsage()
    embeddings = load_embeddings(_fake_settings(), run)

    await embeddings.aembed_documents(["ATP", "DNA"])
    await embeddings.aembed_query("ATP")

    [usage] = run.roles
    assert (usage.role, usage.calls) == ("embedder", 2)


def test_a_role_that_made_no_calls_is_left_out():
    run = RunUsage()
    run.for_role(Role.JUDGE, "fake")

    assert run.roles == []


async def test_without_a_tracker_nothing_is_counted():
    reply = await load_chat_model(Role.WRITER, _fake_settings()).ainvoke("Hello")

    assert reply.content


# --- limits -------------------------------------------------------------------------------


def test_each_model_can_have_its_own_limit():
    settings = _fake_settings(ai_model_daily_limit=18, ai_model_daily_limits="lite:450, flash:9")

    assert settings.model_daily_limit("lite") == 450
    assert settings.model_daily_limit("flash") == 9
    assert settings.model_daily_limit("other") == 18


def test_a_real_model_is_named_for_its_setting():
    settings = Settings(ai_writer_provider="gemini", ai_writer_model="lite")

    assert model_name(Role.WRITER, settings) == "lite"


async def test_a_model_has_room_up_to_its_limit(session, budget, me):
    session.add(_spent(me, 15))
    await session.commit()
    service = budget(ai_model_daily_limit=18, ai_model_daily_limits="other:1")

    assert await service.within_model_limits({Role.WRITER: 3})
    assert not await service.within_model_limits({Role.WRITER: 4})


async def test_roles_on_the_same_model_share_its_limit(budget):
    service = budget(ai_model_daily_limit=4, ai_model_daily_limits="other:1")

    cost = {Role.WRITER: 3, Role.JUDGE: 2}

    assert not await service.within_model_limits(cost, judged=Role.WRITER)


async def test_a_reserve_leaves_room_for_others(session, budget, me):
    session.add(_spent(me, 10))
    await session.commit()
    service = budget(ai_model_daily_limit=18, ai_model_daily_limits="other:1")

    assert not await service.within_model_limits({Role.WRITER: 1}, reserve=9)


async def test_old_usage_doesnt_count(session, budget, me):
    session.add(_spent(me, 18, hours_ago=25))
    await session.commit()
    service = budget(ai_model_daily_limit=18, ai_model_daily_limits="other:1")

    assert await service.within_model_limits({Role.WRITER: 18})


async def test_spending_on_one_model_leaves_the_other_alone(session, budget, me):
    session.add(_spent(me, 18, model="another-model"))
    await session.commit()
    service = budget(ai_model_daily_limit=18, ai_model_daily_limits="other:1")

    assert await service.within_model_limits({Role.WRITER: 18})


async def test_feature_calls_can_be_for_one_user_or_the_site(
    session, budget, me, make_user
):
    other = await make_user(email="other@example.com")
    session.add_all(
        [
            _spent(me, 2, feature=PROBLEM_CARDS),
            _spent(other, 3, feature=PROBLEM_CARDS),
            _spent(me, 9, feature=GENERATE),
        ]
    )
    await session.commit()
    service = budget()

    assert await service.feature_calls(PROBLEM_CARDS, me.id) == (5, 2)
    assert await service.user_feature_calls(PROBLEM_CARDS, me.id) == 2
    assert await service.feature_calls("unused", me.id) == (0, 0)


@pytest.mark.parametrize(
    ("limits", "expected"),
    [
        ({"user_limit": 10, "site_limit": 10}, None),
        ({"user_limit": 10, "site_limit": 5}, SITE),
        ({"user_limit": 2, "site_limit": 10}, USER),
        ({"user_limit": 2}, USER),
    ],
)
async def test_the_first_limit_a_run_would_pass_is_named(
    session, budget, me, make_user, limits, expected
):
    other = await make_user(email="other@example.com")
    session.add_all([_spent(me, 2, feature=PROBLEM_CARDS), _spent(other, 3, feature=PROBLEM_CARDS)])
    await session.commit()

    reached, _ = await budget().limit_reached(PROBLEM_CARDS, me.id, {Role.WRITER: 1}, **limits)

    assert reached == expected


async def test_a_full_model_counts_as_the_site_limit(session, budget, me):
    session.add(_spent(me, 18))
    await session.commit()
    service = budget(ai_model_daily_limit=18, ai_model_daily_limits="other:1")

    reached, choice = await service.limit_reached(GENERATE, me.id, {Role.WRITER: 1}, user_limit=100)

    assert (reached, choice) == (SITE, None)


# --- saving -------------------------------------------------------------------------------


async def test_a_run_saves_a_row_per_role(session, budget, me, make_deck):
    deck = await make_deck(me)
    run = RunUsage()
    settings = _fake_settings()
    models = first_models(settings, [Role.WRITER, Role.JUDGE], judged=Role.WRITER)
    await load_chat_model(Role.WRITER, settings, run).ainvoke("Hello")
    await load_chat_model(Role.JUDGE, settings, run, models=models).ainvoke("Hello")

    budget().record(GENERATE, me.id, deck.id, run, prompt_version="abc")
    await session.commit()

    rows = (await session.scalars(select(AiUsage).order_by(AiUsage.role))).all()
    assert [(row.role, row.calls, row.input_tokens) for row in rows] == [
        ("judge", 1, 10),
        ("writer", 1, 10),
    ]
    assert rows[0].feature == GENERATE
    assert rows[0].deck_id == deck.id
    assert rows[0].prompt_version == "abc"


async def test_recording_doesnt_commit(session, budget, me):
    run = RunUsage()
    await load_chat_model(Role.WRITER, _fake_settings(), run).ainvoke("Hello")

    budget().record(GENERATE, me.id, None, run)
    await session.rollback()

    assert await session.scalar(select(AiUsage)) is None


# --- falling back -------------------------------------------------------------------------


@pytest.fixture
def chained(session):
    """Writer a -> b -> c and judge j -> a -> b -> c, five calls a day each."""
    settings = Settings(
        ai_writer_provider="gemini",
        ai_writer_model="a",
        ai_writer_fallbacks="gemini:b,gemini:c",
        ai_judge_provider="gemini",
        ai_judge_model="j",
        ai_judge_fallbacks="gemini:a,gemini:b,gemini:c",
        ai_model_daily_limits="a:5,b:5,c:5,j:5",
        gemini_api_key="not-a-real-key",
    )
    return BudgetService(UsageRepository(session), settings)


async def test_a_full_model_falls_back_to_the_next(session, chained, me):
    session.add(_spent(me, 5, model="a"))
    await session.commit()

    models = await chained.pick_models({Role.WRITER: 3})

    assert models.chain(Role.WRITER) == (ModelSpec("gemini", "b"), ModelSpec("gemini", "c"))


async def test_the_judge_falls_back_only_to_models_above_the_writer(session, chained, me):
    session.add_all([_spent(me, 3, model="a"), _spent(me, 5, model="j")])
    await session.commit()

    models = await chained.pick_models({Role.JUDGE: 2, Role.WRITER: 3}, judged=Role.WRITER)

    assert models.chain(Role.WRITER) == (ModelSpec("gemini", "b"), ModelSpec("gemini", "c"))
    assert models.chain(Role.JUDGE) == (ModelSpec("gemini", "a"),)


async def test_a_full_judge_moves_the_writer_down_so_another_judge_ranks_above(
    session, chained, me
):
    session.add(_spent(me, 5, model="j"))
    await session.commit()

    models = await chained.pick_models({Role.WRITER: 3, Role.JUDGE: 1}, judged=Role.WRITER)

    assert models.chain(Role.WRITER) == (ModelSpec("gemini", "b"), ModelSpec("gemini", "c"))
    assert models.chain(Role.JUDGE) == (ModelSpec("gemini", "a"),)


async def test_no_judge_above_any_writer_start_means_no_room(session, chained, me):
    session.add_all([_spent(me, 5, model=model) for model in "jab"])
    await session.commit()

    assert await chained.pick_models({Role.WRITER: 3, Role.JUDGE: 1}, judged=Role.WRITER) is None


async def test_no_model_left_means_no_room(session, chained, me):
    session.add_all([_spent(me, 5, model=model) for model in "abc"])
    await session.commit()

    assert await chained.pick_models({Role.WRITER: 1}) is None
    assert not await chained.within_model_limits({Role.WRITER: 1})
