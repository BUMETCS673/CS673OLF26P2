"""B2: GeminiProvider, the one real call to Google.

One test per acceptance example under B2 in code/plans/ITERATION_3_PLAN.md. Nothing here
reaches the network (rule 16): every provider is handed a fake client whose
`models.generate_content` records what it was asked and returns, or raises, what the
test needs. The one test that builds a real client patches `genai.Client` first.
"""

# AI Utilization: ~100% of this file's code
# AI Tools Used: Claude Code (Claude Opus 5.5)
# AI-Assisted Activities:
#   Unit test creation (from the plan's acceptance examples)
# Human role: plan approval, code review, and hands-on testing by Miles Cameron.

import json
import logging
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest
from google.genai import errors, types

from app.ai.provider import AIRateLimited, AIUnavailable, Attachment, GeminiProvider, Prompt

MODEL = "gemini-test-flash"


class FakeModels:
    """Stands in for `client.models`: records each call, then answers as told."""

    def __init__(self, text=None, raises=None):
        self.text = text
        self.raises = raises
        self.calls = []

    def generate_content(self, *, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        if self.raises is not None:
            raise self.raises
        return SimpleNamespace(text=self.text)


def _provider(text=None, raises=None):
    models = FakeModels(text=text, raises=raises)
    return GeminiProvider("not-a-real-key", MODEL, client=SimpleNamespace(models=models)), models


def _prompt(max_cards=4, attachment=None):
    return Prompt(
        system="Write 4 cards.",
        text="Deck name: Anatomy\n\n<source>\nThe bones of the hand\n</source>",
        max_cards=max_cards,
        attachment=attachment,
    )


def _api_error(kind, code, status, message):
    return kind(code, {"error": {"code": code, "message": message, "status": status}})


# --- the call ----------------------------------------------------------------------------


def test_a_reply_returns_its_cards_and_the_call_carries_the_prompt():
    cards = [{"front": "a", "back": "b"}]
    provider, models = _provider(text=json.dumps({"cards": cards}))
    prompt = _prompt(max_cards=4)

    assert provider.generate_cards(prompt) == cards

    [call] = models.calls
    assert call["model"] == MODEL == provider.name
    assert call["contents"] == [prompt.text]
    assert call["config"].system_instruction == prompt.system
    assert call["config"].response_mime_type == "application/json"
    assert call["config"].response_json_schema["properties"]["cards"]["maxItems"] == 4


def test_a_pdf_travels_as_a_part_after_the_text():
    pdf = b"%PDF-1.7\n1 0 obj\n"
    provider, models = _provider(text='{"cards": []}')

    provider.generate_cards(_prompt(attachment=Attachment(mime_type="application/pdf", data=pdf)))

    text, part = models.calls[0]["contents"]
    assert text == _prompt().text
    assert isinstance(part, types.Part)
    assert part.inline_data.mime_type == "application/pdf"
    assert part.inline_data.data == pdf


def test_the_cards_come_back_as_parsed_not_validated():
    """clean_drafts (B1) is what checks them; the provider passes the list through."""
    raw = [{"front": "a"}, {"front": 1, "back": None}, "not a card"]
    provider, _ = _provider(text=json.dumps({"cards": raw}))

    assert provider.generate_cards(_prompt()) == raw


# --- failures (C5) -----------------------------------------------------------------------


def test_googles_429_is_rate_limited():
    error = _api_error(errors.ClientError, 429, "RESOURCE_EXHAUSTED", "quota")
    provider, _ = _provider(raises=error)

    with pytest.raises(AIRateLimited) as raised:
        provider.generate_cards(_prompt())

    assert raised.value.message.startswith("The free AI service is at its limit right now.")


@pytest.mark.parametrize(
    "error",
    [
        _api_error(errors.ClientError, 400, "INVALID_ARGUMENT", "API key not valid."),
        _api_error(errors.ClientError, 403, "PERMISSION_DENIED", "denied"),
        _api_error(errors.ServerError, 503, "UNAVAILABLE", "overloaded"),
        _api_error(errors.ServerError, 500, "INTERNAL", "internal"),
        httpx.ReadTimeout("timed out"),
        httpx.ConnectError("no route"),
        # A 200 whose body isn't JSON, from a proxy say. The SDK raises this as a
        # ValueError, not an APIError, so the plan's table doesn't catch it by itself.
        errors.UnknownApiResponseError("Failed to parse response as JSON."),
    ],
    ids=["400", "403", "503", "500", "timeout", "connect", "unparseable"],
)
def test_any_other_failure_is_unavailable(error):
    provider, _ = _provider(raises=error)

    with pytest.raises(AIUnavailable) as raised:
        provider.generate_cards(_prompt())

    assert raised.value.message == "The AI service didn't respond. Try again in a minute."


@pytest.mark.parametrize(
    "text",
    [None, "", "not json", '{"cards": "nope"}', "{}", '[{"front": "a", "back": "b"}]'],
    ids=["none", "empty", "not-json", "cards-not-a-list", "no-cards", "a-bare-list"],
)
def test_a_reply_without_a_cards_list_is_unavailable(text):
    provider, _ = _provider(text=text)

    with pytest.raises(AIUnavailable):
        provider.generate_cards(_prompt())


def test_failures_are_not_chained_to_the_sdk_error():
    """The SDK error's text carries Google's response body, so it isn't kept as the cause."""
    provider, _ = _provider(raises=_api_error(errors.ClientError, 400, "INVALID_ARGUMENT", "x"))

    with pytest.raises(AIUnavailable) as raised:
        provider.generate_cards(_prompt())

    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__ is True


def test_a_failure_logs_its_type_and_status_and_nothing_the_learner_wrote(caplog):
    """Rule 17: never the prompt, the cards, or str() of an SDK error."""
    body = "API key not valid. Please pass a valid API key."
    provider, _ = _provider(raises=_api_error(errors.ClientError, 400, "INVALID_ARGUMENT", body))

    with caplog.at_level(logging.WARNING), pytest.raises(AIUnavailable):
        provider.generate_cards(_prompt())

    assert "ClientError" in caplog.text
    assert "400" in caplog.text
    assert "INVALID_ARGUMENT" in caplog.text
    assert body not in caplog.text
    assert "bones of the hand" not in caplog.text


def test_an_unusable_reply_logs_without_the_reply(caplog):
    provider, _ = _provider(text='{"cards": "The bones of the hand"}')

    with caplog.at_level(logging.WARNING), pytest.raises(AIUnavailable):
        provider.generate_cards(_prompt())

    assert caplog.text
    assert "bones of the hand" not in caplog.text


# --- building the real client ------------------------------------------------------------


def test_with_no_client_the_real_one_is_built_with_a_45_second_timeout():
    with patch("app.ai.provider.genai.Client") as client_class:
        provider = GeminiProvider("the-key", MODEL)

    client_class.assert_called_once()
    kwargs = client_class.call_args.kwargs
    assert kwargs["api_key"] == "the-key"
    assert kwargs["http_options"].timeout == 45_000  # milliseconds
    assert provider.name == MODEL
