"""The AI provider interface, and the factory that selects a vendor for each role.

Routes call `get_provider().generate_cards(prompt)` and never see a vendor's SDK. Each vendor
subclasses `Provider` in its own module. Every failure leaves as one of the exceptions below, and
the route turns each into the matching error from C5.

Adding a vendor: subclass `Provider`, then add a factory to `_FACTORIES`. Selecting it is then a
settings change: AI_WRITER_PROVIDER, AI_WRITER_MODEL, AI_JUDGE_PROVIDER and AI_JUDGE_MODEL.
"""

# AI Utilization: ~100% of this file's code
# AI Tools Used: Claude Code (Claude Opus 5.5)
# AI-Assisted Activities:
#   AI provider interface and stand-in
# Human role: plan approval, code review, and hands-on testing by Miles Cameron.

import json
import logging
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass

from flask import current_app

logger = logging.getLogger(__name__)

UNAVAILABLE = "The AI service didn't respond. Try again in a minute."
QUOTA_USED_UP = (
    "The free AI service is at its limit right now. Wait a minute and try again. "
    "If it still doesn't work, today's free limit is used up and resets overnight."
)
NOT_CONFIGURED = "AI generation isn't set up on this server."
# Retrying won't help with either of these, so they don't say "try again" (A20).
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


@dataclass
class TokenUsage:
    """Tokens used by one provider instance, summed across its calls."""

    input_tokens: int = 0
    output_tokens: int = 0  # includes thinking tokens, which are billed as output


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


class AITransient(AIUnavailable):
    """A failure that may succeed if retried. Maps to the same 503."""


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


def verdicts_schema(max_cards: int) -> dict:
    """The JSON Schema for judge replies: one verdict per candidate. `reason` is optional."""
    return {
        "type": "object",
        "properties": {
            "verdicts": {
                "type": "array",
                "maxItems": max_cards,
                "items": {
                    "type": "object",
                    "properties": {
                        "index": {"type": "integer"},
                        "ok": {"type": "boolean"},
                        "reason": {"type": "string"},
                    },
                    "required": ["index", "ok"],
                },
            }
        },
        "required": ["verdicts"],
    }


def facts_schema(max_facts: int) -> dict:
    """The JSON Schema for extracted facts."""
    return {
        "type": "object",
        "properties": {
            "facts": {"type": "array", "maxItems": max_facts, "items": {"type": "string"}}
        },
        "required": ["facts"],
    }


def _list_from(text: str | None, key: str) -> list:
    """The `key` list from the model's JSON reply, or AIUnavailable when there isn't one."""
    try:
        reply = json.loads(text)
    except (TypeError, ValueError):  # TypeError: no text at all
        reply = None
    items = reply.get(key) if isinstance(reply, dict) else None
    if not isinstance(items, list):
        logger.warning("ai_provider outcome=unusable_reply")
        raise AIUnavailable()
    return items


class Provider(ABC):
    """A vendor's model. Subclasses implement `_complete()` and map failures to the errors above.

    Instances are created per request, so `usage` is one request's running total.
    """

    def __init__(self, name: str):
        self.name = name  # saved as ai_generations.model
        self.usage = TokenUsage()
        self._usage_lock = threading.Lock()  # extract calls run in parallel threads

    @abstractmethod
    def _complete(self, prompt: Prompt, schema: dict) -> str | None:
        """Make one model call and return the JSON reply text.

        Raises AIRateLimited, AITransient or AIUnavailable.
        """

    def generate_cards(self, prompt: Prompt) -> list:
        """The model's "cards" array, parsed but not validated."""
        return _list_from(self._complete(prompt, cards_schema(prompt.max_cards)), "cards")

    def judge_cards(self, prompt: Prompt) -> list:
        """The model's "verdicts" array, parsed but not validated."""
        return _list_from(self._complete(prompt, verdicts_schema(prompt.max_cards)), "verdicts")

    def extract_facts(self, prompt: Prompt) -> list:
        """The model's "facts" array, parsed but not validated."""
        return _list_from(self._complete(prompt, facts_schema(prompt.max_cards)), "facts")

    def _add_usage(self, input_tokens: int, output_tokens: int) -> None:
        with self._usage_lock:
            self.usage.input_tokens += input_tokens
            self.usage.output_tokens += output_tokens


# Vendor modules are imported inside the factories, so a vendor's SDK loads only when selected.


def _make_fake(model: str) -> Provider:
    from app.ai.fake import FakeProvider

    return FakeProvider()


def _make_gemini(model: str) -> Provider:
    from app.ai.gemini import GeminiProvider

    key = current_app.config["GEMINI_API_KEY"]
    if not key:
        raise AIUnavailable(NOT_CONFIGURED)
    return GeminiProvider(key, model)


_FACTORIES = {"fake": _make_fake, "gemini": _make_gemini}


def get_provider(role: str = "writer") -> Provider:
    """The provider configured for `role`: "writer" or "judge".

    Raises AIUnavailable(NOT_CONFIGURED) for an unknown vendor, or a vendor with no key.
    """
    config = current_app.config
    prefix = f"AI_{role.upper()}"
    factory = _FACTORIES.get(config[f"{prefix}_PROVIDER"])
    if factory is None:
        raise AIUnavailable(NOT_CONFIGURED)
    return factory(config[f"{prefix}_MODEL"])
