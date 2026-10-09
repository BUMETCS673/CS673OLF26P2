"""The one place Cadence talks to an AI model (rule 15).

Routes call `get_provider().generate_cards(prompt)` and never see `google.genai`. That's
what makes the stand-in a one-setting swap (AI_PROVIDER, decision A3), and what keeps the
key in one place. Contract C6 in code/plans/ITERATION_3_PLAN.md.

Step 0a writes everything here except the body of `GeminiProvider.generate_cards()`,
which B2 fills in. Every failure leaves as one of the two exceptions below, and the route
turns each into the matching error from C5.
"""

# AI Utilization: ~100% of this file's code
# AI Tools Used: Claude Code (Claude Opus 5.5)
# AI-Assisted Activities:
#   AI provider interface and stand-in
# Human role: plan approval, code review, and hands-on testing by Miles Cameron.

# B2: GeminiProvider.generate_cards() and its private helpers, _log_failure() and
# _cards_from().
# AI Utilization: ~100% of that code
# AI Tools Used: Claude Code (Claude Opus 5.5)
# AI-Assisted Activities:
#   AI provider integration and error mapping
# Human role: plan approval, code review, and hands-on testing by Miles Cameron.

import itertools
import json
import logging
from dataclasses import dataclass
from typing import Protocol

import httpx
from flask import current_app
from google import genai
from google.genai import errors, types

logger = logging.getLogger(__name__)

UNAVAILABLE = "The AI service didn't respond. Try again in a minute."
QUOTA_USED_UP = (
    "The free AI service is at its limit right now. Wait a minute and try again. "
    "If it still doesn't work, today's free limit is used up and resets overnight."
)
NOT_CONFIGURED = "AI generation isn't set up on this server."
# Retrying won't help with either of these, so they don't say "try again" (A20). B2 raises them.
TOO_MUCH = (
    "That was too much to turn into cards at once. Ask for fewer cards or use a shorter file."
)
DECLINED = "Gemini declined to write cards from that material."


@dataclass(frozen=True)
class CardDraft:
    front: str
    back: str


@dataclass(frozen=True)
class Attachment:
    mime_type: str          # "application/pdf" only. Text files are inlined into the prompt.
    data: bytes


@dataclass(frozen=True)
class Prompt:
    system: str             # the rules, with the count filled in
    text: str               # the deck context plus the mode's body
    max_cards: int          # the requested count; the schema's maxItems
    attachment: Attachment | None = None


class AIRateLimited(Exception):
    """The route answers 429 rate_limited with `.message`."""

    def __init__(self, message: str = QUOTA_USED_UP):
        super().__init__(message)
        self.message = message


class AIUnavailable(Exception):
    """The route answers 503 ai_unavailable with `.message`."""

    def __init__(self, message: str = UNAVAILABLE):
        super().__init__(message)
        self.message = message


def cards_schema(max_cards: int) -> dict:
    """The JSON Schema the model must answer with."""
    return {
        "type": "object",
        "properties": {
            "cards": {
                "type": "array",
                "maxItems": max_cards,
                "items": {
                    "type": "object",
                    "properties": {"front": {"type": "string"}, "back": {"type": "string"}},
                    "required": ["front", "back"],
                },
            }
        },
        "required": ["cards"],
    }


class Provider(Protocol):
    name: str               # saved as ai_generations.model

    def generate_cards(self, prompt: Prompt) -> list:
        """The model's "cards" array, parsed but not validated. Raises AIRateLimited or AIUnavailable."""


# One counter for the whole process, so a second batch never repeats the first one's
# fronts. If it did, cleanup would drop them as copies of cards already accepted.
_sample_numbers = itertools.count(1)


class FakeProvider:
    """The stand-in: tests, development without a key, and the demo fallback (A3)."""

    name = "fake"

    def __init__(self, fail_with: type[Exception] | None = None):
        self.fail_with = fail_with

    def generate_cards(self, prompt: Prompt) -> list:
        if self.fail_with is not None:
            raise self.fail_with()
        numbers = [next(_sample_numbers) for _ in range(prompt.max_cards)]
        return [{"front": f"Sample question {n}", "back": f"Sample answer {n}"} for n in numbers]


class GeminiProvider:
    """Google's Gemini, on the free tier (A1). Billing is never turned on (A2)."""

    def __init__(self, api_key: str, model: str, client=None):
        self.name = model
        # `client` lets tests pass a fake. The SDK's timeout is in milliseconds: 45 s is
        # under nginx's 60 s, so a slow reply ends as our 503, not nginx's 504.
        if client is None:
            client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=45_000))
        self._client = client

    def generate_cards(self, prompt: Prompt) -> list:
        contents = [prompt.text]
        if prompt.attachment:
            contents.append(
                types.Part.from_bytes(
                    data=prompt.attachment.data, mime_type=prompt.attachment.mime_type
                )
            )
        config = types.GenerateContentConfig(
            system_instruction=prompt.system,
            response_mime_type="application/json",
            response_json_schema=cards_schema(prompt.max_cards),
        )
        # One attempt: the SDK doesn't retry unless asked to, and a retry would spend the
        # free quota twice. `from None` drops the SDK error, whose text carries Google's
        # response body, so no traceback can log it later (rule 17).
        try:
            response = self._client.models.generate_content(
                model=self.name, contents=contents, config=config
            )
        except errors.ClientError as error:
            _log_failure(error)
            if error.code == 429:
                raise AIRateLimited() from None
            raise AIUnavailable() from None  # a 400 for a bad key, for example
        # UnknownApiResponseError is a 200 whose body isn't JSON. The SDK raises it as a
        # ValueError rather than an APIError, so it's named on its own. httpx.HTTPError
        # covers every timeout and lost connection.
        except (errors.APIError, errors.UnknownApiResponseError, httpx.HTTPError) as error:
            _log_failure(error)
            raise AIUnavailable() from None
        return _cards_from(response.text)


def _log_failure(error: Exception) -> None:
    """Rule 17: the type and the status, never str(error), which carries the response."""
    logger.warning(
        "ai_provider outcome=error type=%s code=%s status=%s",
        type(error).__name__,
        getattr(error, "code", None),
        getattr(error, "status", None),
    )


def _cards_from(text: str | None) -> list:
    """The "cards" list from the model's JSON reply, or AIUnavailable when there isn't one."""
    try:
        reply = json.loads(text)
    except (TypeError, ValueError):  # TypeError: no text at all
        reply = None
    cards = reply.get("cards") if isinstance(reply, dict) else None
    if not isinstance(cards, list):
        logger.warning("ai_provider outcome=unusable_reply")
        raise AIUnavailable()
    return cards


def get_provider() -> Provider:
    """The provider AI_PROVIDER names.

    Raises AIUnavailable(NOT_CONFIGURED) when it names Gemini with no key, or names
    something else entirely.
    """
    config = current_app.config
    if config["AI_PROVIDER"] == "fake":
        return FakeProvider()
    if config["AI_PROVIDER"] == "gemini" and config["GEMINI_API_KEY"]:
        return GeminiProvider(config["GEMINI_API_KEY"], config["GEMINI_MODEL"])
    raise AIUnavailable(NOT_CONFIGURED)
