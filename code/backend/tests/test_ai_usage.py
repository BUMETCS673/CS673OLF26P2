"""Counting what a run spends, budgets, and saving usage."""

from datetime import timedelta

import pytest
from langchain_core.outputs import ChatResult
from sqlalchemy import select

from app.ai.fake import FakeChatModel
from app.ai.models import Role, load_chat_model, load_embeddings, model_name
from app.ai.schemas import CardBatch
from app.ai.usage import RunUsage
from app.core.settings import Settings
from app.models import AiUsage, utcnow
from app.repositories.usage import UsageRepository
from app.services.budget import GENERATE, PROBLEM_CARDS, BudgetService


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

    await load_chat_model(Role.WRITER, settings, run).ainvoke("Hello")
    await load_chat_model(Role.JUDGE, settings, run).ainvoke("Hello")
    await load_chat_model(Role.JUDGE, settings, run).ainvoke("Hello")

    assert {usage.role: usage.calls for usage in run.roles} == {"writer": 1, "judge": 2}


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

    assert not await service.within_model_limits({Role.WRITER: 3, Role.JUDGE: 2})


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


# --- saving -------------------------------------------------------------------------------


async def test_a_run_saves_a_row_per_role(session, budget, me, make_deck):
    deck = await make_deck(me)
    run = RunUsage()
    settings = _fake_settings()
    await load_chat_model(Role.WRITER, settings, run).ainvoke("Hello")
    await load_chat_model(Role.JUDGE, settings, run).ainvoke("Hello")

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
