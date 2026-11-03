"""The AI provider interface, and the factory that selects a vendor for each role.

Features call `get_provider().complete_json(prompt, schema)` with their own prompt and schema, and
never see a vendor's SDK. Each vendor subclasses `Provider` in its own module. Every failure leaves
as one of the exceptions below, and the route turns each into the matching error from C5.

Adding a vendor: subclass `Provider`, then add a factory to `_FACTORIES`. Adding a feature needs no
change here. Selecting a vendor is a settings change, per role: AI_<ROLE>_PROVIDER, AI_<ROLE>_MODEL
and AI_<ROLE>_THINKING.
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
from enum import StrEnum

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
DECLINED = "The AI declined to write cards from that material."


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
    system: str             # the rules
    text: str               # the request's data
    attachment: Attachment | None = None


@dataclass
class TokenUsage:
    """Tokens used by one provider instance, summed across its calls."""

    input_tokens: int = 0
    output_tokens: int = 0  # includes thinking tokens, which are billed as output
    calls: int = 0          # every attempt, including ones that failed


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


def _unusable_reply() -> AIUnavailable:
    logger.warning("ai_provider outcome=unusable_reply")
    return AIUnavailable()


def list_from(reply: dict, key: str) -> list:
    """The `key` list from a reply, or AIUnavailable when there isn't one."""
    items = reply.get(key)
    if not isinstance(items, list):
        raise _unusable_reply()
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

    def complete_json(self, prompt: Prompt, schema: dict) -> dict:
        """Make one model call and return the reply, parsed but not validated against `schema`.

        Raises AIRateLimited, AITransient or AIUnavailable, including when the reply isn't a JSON
        object.
        """
        with self._usage_lock:
            self.usage.calls += 1
        try:
            reply = json.loads(self._complete(prompt, schema))
        except (TypeError, ValueError):  # TypeError: no text at all
            raise _unusable_reply() from None
        if not isinstance(reply, dict):
            raise _unusable_reply()
        return reply

    def _add_usage(self, input_tokens: int, output_tokens: int) -> None:
        with self._usage_lock:
            self.usage.input_tokens += input_tokens
            self.usage.output_tokens += output_tokens


class Role(StrEnum):
    """What a provider is used for. Each role has its own settings."""

    WRITER = "writer"
    JUDGE = "judge"


@dataclass(frozen=True)
class RoleSettings:
    vendor: str
    model: str
    thinking: str  # a vendor's effort level, such as "low"


def _settings(role: Role) -> RoleSettings:
    config = current_app.config
    prefix = f"AI_{Role(role).name}"
    return RoleSettings(
        config[f"{prefix}_PROVIDER"], config[f"{prefix}_MODEL"], config[f"{prefix}_THINKING"]
    )


# Vendor modules are imported inside the factories, so a vendor's SDK loads only when selected.


def _make_fake(settings: RoleSettings) -> Provider:
    from app.ai.fake import FakeProvider

    return FakeProvider()


def _make_gemini(settings: RoleSettings) -> Provider:
    from app.ai.gemini import GeminiProvider

    key = current_app.config["GEMINI_API_KEY"]
    if not key:
        raise AIUnavailable(NOT_CONFIGURED)
    try:
        return GeminiProvider(key, settings.model, thinking=settings.thinking)
    except ValueError:  # an unknown thinking level
        raise AIUnavailable(NOT_CONFIGURED) from None


_FACTORIES = {"fake": _make_fake, "gemini": _make_gemini}
_REQUIRED_KEYS = {"gemini": "GEMINI_API_KEY"}


def is_configured(role: Role = Role.WRITER) -> bool:
    """Whether get_provider(role) should succeed, without building a vendor client."""
    vendor = _settings(role).vendor
    key = _REQUIRED_KEYS.get(vendor)
    return vendor in _FACTORIES and (key is None or bool(current_app.config[key]))


def model_name(role: Role = Role.WRITER) -> str:
    """The name `role`'s provider reports as `.name`, without building a vendor client."""
    settings = _settings(role)
    return "fake" if settings.vendor == "fake" else settings.model


def get_provider(role: Role = Role.WRITER) -> Provider:
    """The provider configured for `role`.

    Raises AIUnavailable(NOT_CONFIGURED) for an unknown vendor, or a vendor with no key.
    """
    settings = _settings(role)
    factory = _FACTORIES.get(settings.vendor)
    if factory is None:
        raise AIUnavailable(NOT_CONFIGURED)
    return factory(settings)
