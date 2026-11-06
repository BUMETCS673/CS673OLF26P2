"""Loading models, the stand-ins, and mapping vendor errors."""

import httpx
import pytest
from google.genai import errors
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableWithFallbacks
from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain_google_genai._common import GoogleGenerativeAIError
from langchain_google_genai.chat_models import (
    ChatGoogleGenerativeAIError,
    GoogleAPIError,
    GoogleRateLimitError,
)

from app.ai.failures import FALL_BACK_ON
from app.ai.fake import FakeChatModel, FakeEmbeddings
from app.ai.models import (
    NOT_CONFIGURED,
    AIRateLimited,
    AITransient,
    AIUnavailable,
    ChainFallbackMiddleware,
    GuardedEmbeddings,
    ModelSpec,
    Role,
    RunModels,
    agent_model,
    ai_errors,
    check_model_chains,
    first_models,
    judge_chain,
    load_chat_model,
    load_embeddings,
    model_chain,
    plan_models,
    structured_reply,
)
from app.ai.models.calls import _with_schema
from app.ai.rate_limits import ModelBusy
from app.ai.schemas import CardBatch, Verdicts
from app.core.settings import EMBEDDING_DIMENSIONS, Settings


def _settings(**values):
    defaults = {
        "ai_writer_provider": "gemini",
        "ai_judge_provider": "gemini",
        "ai_embedder_provider": "gemini",
        "gemini_api_key": "not-a-real-key",
        "ai_model_rate_limits": "",
    }
    return Settings(**{**defaults, **values})


def _api_error(kind, code):
    return kind(code, {"error": {"code": code, "message": "private text", "status": "X"}})


@tool
def look_up(query: str) -> str:
    """Look something up."""
    return query


@tool
def finish(answer: str) -> str:
    """Finish."""
    return answer


# --- loading ------------------------------------------------------------------------------


def test_each_role_has_its_own_model():
    settings = _settings(
        ai_writer_model="lite",
        ai_judge_model="flash",
        ai_judge_fallbacks="gemini:lite",
        ai_helper_provider="gemini",
        ai_helper_model="mini",
    )

    models = first_models(settings, [Role.WRITER, Role.JUDGE], judged=Role.WRITER)

    assert load_chat_model(Role.WRITER, settings).model.endswith("lite")
    assert load_chat_model(Role.JUDGE, settings, models=models).model.endswith("flash")
    assert load_chat_model(Role.HELPER, settings).model.endswith("mini")


def test_the_real_chat_model_makes_one_attempt_with_our_settings():
    model = load_chat_model(Role.WRITER, _settings(ai_writer_fallbacks=""))

    assert isinstance(model, ChatGoogleGenerativeAI)
    assert model.max_retries == 1
    assert model.timeout == 45
    assert model.temperature is None


@pytest.mark.parametrize(
    ("model", "level"), [("gemini-3.5-flash-lite", "low"), ("gemini-2.5-flash-lite", None)]
)
def test_only_gemini_3_gets_a_thinking_level(model, level):
    settings = _settings(ai_writer_model=model, ai_writer_fallbacks="")

    assert load_chat_model(Role.WRITER, settings).thinking_level == level


def test_a_role_lists_its_own_model_first_then_its_fallbacks():
    settings = _settings(
        ai_writer_model="lite",
        ai_writer_fallbacks="gemini:big, gemini:small, gemini:lite",
    )

    assert model_chain(Role.WRITER, settings) == [
        ModelSpec("gemini", "lite"),
        ModelSpec("gemini", "big"),
        ModelSpec("gemini", "small"),
    ]


def test_a_fallback_that_isnt_set_up_is_skipped():
    settings = _settings(ai_writer_model="lite", ai_writer_fallbacks="not-a-vendor:big")

    assert model_chain(Role.WRITER, settings) == [ModelSpec("gemini", "lite")]


def test_a_role_with_later_models_gets_them_as_fallbacks():
    settings = _settings(ai_writer_fallbacks="gemini:big,gemini:small")

    model = load_chat_model(Role.WRITER, settings)

    assert isinstance(model, RunnableWithFallbacks)
    assert isinstance(model.runnable, ChatGoogleGenerativeAI)
    assert [fallback.model.split("/")[-1] for fallback in model.fallbacks] == ["big", "small"]
    assert model.exceptions_to_handle == FALL_BACK_ON


def _spec(name):
    return ModelSpec("gemini", name)


def _ranked(**values):
    """A judge ranking big > mid > small > tiny."""
    return _settings(
        ai_judge_model="big", ai_judge_fallbacks="gemini:mid,gemini:small,gemini:tiny", **values
    )


def test_the_judge_chain_stops_above_every_model_it_checks():
    # A chain that isn't strongest first, like the helper's, still ranks by its strongest.
    above = judge_chain(_ranked(), [_spec("small"), _spec("mid")])

    assert above == [_spec("big")]


def test_the_judge_plans_above_every_model_the_helper_may_fall_back_to():
    settings = _ranked(
        ai_helper_provider="gemini", ai_helper_model="small", ai_helper_fallbacks="gemini:mid"
    )

    models = plan_models(settings, [Role.HELPER, Role.JUDGE], judged=Role.HELPER)

    assert models.chain(Role.HELPER) == (_spec("small"), _spec("mid"))
    assert models.chain(Role.JUDGE) == (_spec("big"),)


def test_the_judge_falls_back_only_above_the_writer():
    settings = _ranked(ai_writer_model="small", ai_writer_fallbacks="")
    models = first_models(settings, [Role.WRITER, Role.JUDGE], judged=Role.WRITER)

    judge = load_chat_model(Role.JUDGE, settings, models=models)

    assert [fallback.model.split("/")[-1] for fallback in judge.fallbacks] == ["mid"]


def test_a_judge_with_nothing_above_the_writer_isnt_set_up():
    settings = _ranked(ai_writer_model="big", ai_writer_fallbacks="")

    with pytest.raises(AIUnavailable, match=NOT_CONFIGURED):
        first_models(settings, [Role.WRITER, Role.JUDGE], judged=Role.WRITER)


def test_a_run_with_a_judge_must_say_what_it_checks():
    with pytest.raises(ValueError):
        plan_models(_settings(), [Role.WRITER, Role.JUDGE])
    with pytest.raises(ValueError):
        load_chat_model(Role.JUDGE, _settings())


def test_the_default_chains_pass_the_startup_check():
    check_model_chains(_settings(ai_helper_provider="gemini"))


@pytest.mark.parametrize("writer", ["big", "unranked"])
def test_a_judge_that_cant_rank_above_the_writer_stops_startup(writer):
    settings = _ranked(ai_writer_model=writer, ai_writer_fallbacks="")

    with pytest.raises(ValueError, match=writer):
        check_model_chains(settings)


def test_the_startup_check_waits_for_the_ai_to_be_set_up():
    check_model_chains(_ranked(ai_writer_model="unranked", gemini_api_key=""))


class BusyModel(FakeChatModel):
    def _generate(self, *_, **__):
        raise ModelBusy()


class OverloadedModel(FakeChatModel):
    def _generate(self, *_, **__):
        raise _api_error(GoogleAPIError, 503)


class BrokenModel(FakeChatModel):
    def _generate(self, *_, **__):
        raise ValueError("not a limit")


@pytest.mark.parametrize("first", [BusyModel, OverloadedModel])
async def test_a_rate_limited_or_overloaded_call_is_answered_by_the_next_model(first):
    model = first().with_fallbacks([FakeChatModel()], exceptions_to_handle=FALL_BACK_ON)

    reply = await structured_reply(model, CardBatch, [HumanMessage("Write cards.")])

    assert isinstance(reply, CardBatch)


async def test_other_failures_dont_fall_back():
    model = BrokenModel().with_fallbacks([FakeChatModel()], exceptions_to_handle=FALL_BACK_ON)

    with pytest.raises(ValueError):
        await structured_reply(model, CardBatch, [HumanMessage("Write cards.")])


def test_an_agent_gets_the_fallbacks_as_middleware():
    first, fallback = FakeChatModel(), FakeChatModel()

    model, [middleware] = agent_model(first.with_fallbacks([fallback]))

    assert model is first
    assert isinstance(middleware, ChainFallbackMiddleware)
    assert middleware.models == [fallback]
    assert agent_model(first) == (first, [])


class _Request:
    def __init__(self, model):
        self.model = model

    def override(self, model):
        return _Request(model)


@pytest.mark.parametrize(
    ("error", "answered_by"),
    [(ModelBusy(), "later"), (_api_error(GoogleAPIError, 503), "later"), (ValueError(), None)],
)
async def test_an_agent_falls_back_only_where_another_model_can_answer(error, answered_by):
    async def handler(request):
        if request.model == "first":
            raise error
        return request.model

    middleware = ChainFallbackMiddleware(["later"])

    if answered_by is None:
        with pytest.raises(type(error)):
            await middleware.awrap_model_call(_Request("first"), handler)
    else:
        assert await middleware.awrap_model_call(_Request("first"), handler) == answered_by


def test_a_fake_role_has_no_fallbacks():
    settings = Settings(ai_writer_provider="fake", ai_writer_fallbacks="gemini:big")

    assert model_chain(Role.WRITER, settings) == [ModelSpec("fake", "fake")]


@pytest.mark.parametrize(
    ("model", "through_a_tool"), [("gemma-4-31b-it", True), ("gemini-3.5-flash-lite", False)]
)
def test_only_gemma_replies_in_a_schema_through_a_tool_call(model, through_a_tool):
    models = RunModels({Role.HELPER: (ModelSpec("gemini", model),)})
    chat = load_chat_model(Role.HELPER, _settings(), models=models)

    structured = _with_schema(chat, CardBatch)

    assert ("tools" in structured.first.kwargs) is through_a_tool


def test_a_picked_model_is_loaded_instead_of_the_first():
    models = RunModels({Role.WRITER: (ModelSpec("gemini", "big"),)})

    model = load_chat_model(Role.WRITER, _settings(), models=models)

    assert isinstance(model, ChatGoogleGenerativeAI)
    assert model.model.endswith("big")


def test_the_real_embeddings_use_our_vector_size():
    embeddings = load_embeddings(_settings())

    assert isinstance(embeddings, GuardedEmbeddings)
    assert isinstance(embeddings.embeddings, GoogleGenerativeAIEmbeddings)
    assert embeddings.embeddings.output_dimensionality == EMBEDDING_DIMENSIONS


def test_fake_is_a_setting():
    settings = Settings(ai_writer_provider="fake", ai_embedder_provider="fake")

    assert isinstance(load_chat_model(Role.WRITER, settings), FakeChatModel)
    assert isinstance(load_embeddings(settings), FakeEmbeddings)


@pytest.mark.parametrize(
    "settings",
    [
        Settings(ai_writer_provider="gemini", ai_embedder_provider="gemini", gemini_api_key=""),
        Settings(ai_writer_provider="not-a-vendor", ai_embedder_provider="not-a-vendor"),
    ],
)
def test_a_model_that_isnt_set_up_is_unavailable(settings):
    with pytest.raises(AIUnavailable, match=NOT_CONFIGURED):
        load_chat_model(Role.WRITER, settings)
    with pytest.raises(AIUnavailable, match=NOT_CONFIGURED):
        load_embeddings(settings)


def test_a_blank_setting_falls_back_to_the_default(monkeypatch):
    monkeypatch.setenv("AI_WRITER_MODEL", "")

    assert Settings().ai_writer_model == Settings.model_fields["ai_writer_model"].default


# --- the stand-ins ------------------------------------------------------------------------


async def test_the_stand_in_fills_in_structured_output():
    result = await FakeChatModel().with_structured_output(CardBatch).ainvoke("Write cards")

    assert isinstance(result, CardBatch)
    assert result.cards[0].front.startswith("Sample question")
    assert result.cards[0].back.startswith("Sample answer")


async def test_a_card_and_its_answer_share_a_number():
    result = await FakeChatModel().with_structured_output(CardBatch).ainvoke("Write cards")

    card = result.cards[0]
    assert card.front.split()[-1] == card.back.split()[-1]
    assert result.cards[0].front != result.cards[1].front


async def test_the_stand_in_approves_each_position():
    result = await FakeChatModel().with_structured_output(Verdicts).ainvoke("Check cards")

    assert [v.index for v in result.verdicts[:3]] == [0, 1, 2]
    assert all(v.ok for v in result.verdicts)


async def test_the_stand_in_calls_the_last_tool():
    model = FakeChatModel().bind_tools([look_up, finish])

    reply = await model.ainvoke([HumanMessage("Hello")])

    assert reply.tool_calls[0]["name"] == "finish"


async def test_the_stand_in_obeys_a_required_tool():
    model = FakeChatModel().bind_tools([look_up, finish], tool_choice="look_up")

    reply = await model.ainvoke([HumanMessage("Hello")])

    assert reply.tool_calls[0]["name"] == "look_up"


async def test_the_stand_in_reports_token_usage():
    reply = await FakeChatModel().ainvoke("Hello")

    assert reply.usage_metadata["total_tokens"] == 15


async def test_the_same_text_gets_the_same_vector():
    embeddings = FakeEmbeddings()

    first, other, again = await embeddings.aembed_documents(["ATP", "DNA", "ATP"])

    assert len(first) == EMBEDDING_DIMENSIONS
    assert first == again
    assert first != other
    assert await embeddings.aembed_query("ATP") == first


# --- errors -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raised", "expected"),
    [
        (GoogleRateLimitError("slow down"), AIRateLimited),
        (ChatGoogleGenerativeAIError("bad key"), AIUnavailable),
        (_api_error(errors.ClientError, 429), AIRateLimited),
        (_api_error(errors.ClientError, 400), AIUnavailable),
        (_api_error(errors.ServerError, 503), AITransient),
        (_api_error(errors.ServerError, 501), AIUnavailable),
        (_api_error(errors.ServerError, 504), AITransient),
        (httpx.ConnectError("offline"), AITransient),
        (httpx.ReadTimeout("slow"), AIUnavailable),
    ],
)
def test_vendor_failures_become_our_errors(raised, expected):
    def hides_the_vendor_error(error):
        return type(error) is expected and "private" not in str(error) and error.__cause__ is None

    with pytest.raises(expected, check=hides_the_vendor_error), ai_errors():
        raise raised


def test_a_failure_is_logged_by_its_kind_class_and_status(caplog):
    def logs_the_failure(_error):
        [line] = [record for record in caplog.records if record.getMessage() == "ai call failed"]
        assert (line.failure, line.vendor_error, line.status) == ("overloaded", "ServerError", 503)
        assert "private" not in caplog.text
        return True

    with pytest.raises(AITransient, check=logs_the_failure), ai_errors():
        raise _api_error(errors.ServerError, 503)


@pytest.mark.parametrize(
    ("cause", "expected"),
    [
        (_api_error(errors.ClientError, 429), AIRateLimited),
        (_api_error(errors.ServerError, 503), AITransient),
    ],
)
def test_a_wrapped_error_from_embeddings_is_read_by_its_status(cause, expected):
    wrapped = GoogleGenerativeAIError("failed")
    wrapped.__cause__ = cause

    with pytest.raises(expected), ai_errors():
        raise wrapped


def test_other_errors_pass_through():
    with pytest.raises(ValueError), ai_errors():
        raise ValueError("a bug")
