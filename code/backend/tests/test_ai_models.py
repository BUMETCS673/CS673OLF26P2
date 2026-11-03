"""Loading models, the stand-ins, and mapping vendor errors."""

import httpx
import pytest
from google.genai import errors
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain_google_genai._common import GoogleGenerativeAIError
from langchain_google_genai.chat_models import ChatGoogleGenerativeAIError, GoogleRateLimitError

from app.ai.fake import FakeChatModel, FakeEmbeddings
from app.ai.models import (
    NOT_CONFIGURED,
    AIRateLimited,
    AITransient,
    AIUnavailable,
    Role,
    ai_errors,
    load_chat_model,
    load_embeddings,
)
from app.ai.schemas import CardBatch, Verdicts
from app.core.settings import EMBEDDING_DIMENSIONS, Settings


def _settings(**values):
    return Settings(
        ai_writer_provider="gemini",
        ai_judge_provider="gemini",
        ai_embedder_provider="gemini",
        gemini_api_key="not-a-real-key",
        ai_model_rate_limits="",
        **values,
    )


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
    settings = _settings(ai_writer_model="lite", ai_judge_model="flash")

    assert load_chat_model(Role.WRITER, settings).model.endswith("lite")
    assert load_chat_model(Role.JUDGE, settings).model.endswith("flash")


def test_the_real_chat_model_makes_one_attempt_with_our_settings():
    model = load_chat_model(Role.WRITER, _settings())

    assert isinstance(model, ChatGoogleGenerativeAI)
    assert model.max_retries == 1
    assert model.timeout == 45
    assert model.temperature is None


def test_the_real_embeddings_use_our_vector_size():
    embeddings = load_embeddings(_settings())

    assert isinstance(embeddings, GoogleGenerativeAIEmbeddings)
    assert embeddings.output_dimensionality == EMBEDDING_DIMENSIONS


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


def _api_error(kind, code):
    return kind(code, {"error": {"code": code, "message": "private text", "status": "X"}})


@pytest.mark.parametrize(
    ("raised", "expected"),
    [
        (GoogleRateLimitError("slow down"), AIRateLimited),
        (ChatGoogleGenerativeAIError("bad key"), AIUnavailable),
        (_api_error(errors.ClientError, 429), AIRateLimited),
        (_api_error(errors.ClientError, 400), AIUnavailable),
        (_api_error(errors.ServerError, 503), AITransient),
        (_api_error(errors.ServerError, 501), AIUnavailable),
        (httpx.ConnectError("offline"), AITransient),
        (httpx.ReadTimeout("slow"), AIUnavailable),
    ],
)
def test_vendor_failures_become_our_errors(raised, expected):
    with pytest.raises(expected) as caught, ai_errors():
        raise raised

    assert type(caught.value) is expected
    assert "private" not in str(caught.value)
    assert caught.value.__cause__ is None


def test_a_wrapped_rate_limit_from_embeddings_is_recognized():
    wrapped = GoogleGenerativeAIError("failed")
    wrapped.__cause__ = _api_error(errors.ClientError, 429)

    with pytest.raises(AIRateLimited), ai_errors():
        raise wrapped


def test_other_errors_pass_through():
    with pytest.raises(ValueError), ai_errors():
        raise ValueError("a bug")
