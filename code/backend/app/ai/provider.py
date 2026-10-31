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

# B2: GeminiProvider.generate_cards() and its private helpers, _log_failure(),
# _check_stop() and _list_from().
# AI Utilization: ~100% of that code
# AI Tools Used: Claude Code (Claude Opus 5.5)
# AI-Assisted Activities:
#   AI provider integration and error mapping
# Human role: plan approval, code review, and hands-on testing by Miles Cameron.

# Self-correcting pipeline: judge_cards(), verdicts_schema() and get_judge_provider().

import itertools
import json
import logging
import threading
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


class AITransient(AIUnavailable):
    """A failure that may succeed if retried. Maps to the same 503."""


# 501 and 504 are excluded: Google advises changing the request or deadline instead. 429 is
# handled separately, because a retry within seconds can't clear a per-minute or daily limit.
_RETRIABLE_STATUS = frozenset({408, 500, 502, 503})


def verdicts_schema(max_cards: int) -> dict:
    """The JSON Schema for judge replies: one verdict per candidate.

    `reason` is optional in the schema, so the caller supplies a fallback when it is missing.
    """
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


class Provider(Protocol):
    name: str               # saved as ai_generations.model
    usage: TokenUsage       # running total; providers are created per request

    def generate_cards(self, prompt: Prompt) -> list:
        """The model's "cards" array, parsed but not validated. Raises AIRateLimited or AIUnavailable."""

    def judge_cards(self, prompt: Prompt) -> list:
        """The model's "verdicts" array, parsed but not validated. Raises the same two errors."""

    def extract_facts(self, prompt: Prompt) -> list:
        """The model's "facts" array, parsed but not validated. Raises the same two errors."""


# One counter for the whole process, so a second batch never repeats the first one's
# fronts. If it did, cleanup would drop them as copies of cards already accepted.
_sample_numbers = itertools.count(1)


class FakeProvider:
    """The stand-in: tests, development without a key, and the demo fallback (A3)."""

    name = "fake"

    def __init__(self, fail_with: type[Exception] | None = None):
        self.fail_with = fail_with
        self.usage = TokenUsage()

    def generate_cards(self, prompt: Prompt) -> list:
        if self.fail_with is not None:
            raise self.fail_with()
        numbers = [next(_sample_numbers) for _ in range(prompt.max_cards)]
        return [{"front": f"Sample question {n}", "back": f"Sample answer {n}"} for n in numbers]

    def judge_cards(self, prompt: Prompt) -> list:
        if self.fail_with is not None:
            raise self.fail_with()
        # Approve every candidate. For a judge prompt, max_cards is the number of candidates.
        return [{"index": index, "ok": True} for index in range(prompt.max_cards)]

    def extract_facts(self, prompt: Prompt) -> list:
        if self.fail_with is not None:
            raise self.fail_with()
        return [f"Sample fact {next(_sample_numbers)}"]


class GeminiProvider:
    """Google's Gemini, on the free tier (A1). Billing is never turned on (A2)."""

    def __init__(self, api_key: str, model: str, client=None):
        self.name = model
        self.usage = TokenUsage()
        self._usage_lock = threading.Lock()  # extract calls run in parallel threads
        # `client` lets tests pass a fake. The SDK's timeout is in milliseconds: six sequential
        # calls at 45 s stay under nginx's 280 s, so a slow reply ends as our 503, not nginx's 504.
        if client is None:
            client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=45_000))
        self._client = client

    def generate_cards(self, prompt: Prompt) -> list:
        return _list_from(self._generate(prompt, cards_schema(prompt.max_cards)), "cards")

    def judge_cards(self, prompt: Prompt) -> list:
        return _list_from(self._generate(prompt, verdicts_schema(prompt.max_cards)), "verdicts")

    def extract_facts(self, prompt: Prompt) -> list:
        return _list_from(self._generate(prompt, facts_schema(prompt.max_cards)), "facts")

    def _generate(self, prompt: Prompt, schema: dict) -> str | None:
        """Make one model call and return the reply text. Raises AIRateLimited or AIUnavailable.

        Shared by generate_cards() and judge_cards(), which differ only in schema and reply key.
        """
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
            response_json_schema=schema,
            # A20: writing cards is simple instruction following, and Gemini 3 models default
            # to high thinking, which is slower. Never send thinking_budget as well: the two
            # together are a 400.
            thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW),
        )
        # One attempt: the SDK doesn't retry unless asked to, and a retry would spend the
        # free quota twice. Only the pipeline's generate node retries, on AITransient. `from None` drops the SDK error, whose text carries Google's
        # response body, so no traceback can log it later (rule 17).
        try:
            response = self._client.models.generate_content(
                model=self.name, contents=contents, config=config
            )
        except errors.ClientError as error:
            _log_failure(error)
            if error.code == 429:
                raise AIRateLimited() from None
            if error.code in _RETRIABLE_STATUS:
                raise AITransient() from None
            raise AIUnavailable() from None  # a 400 for a bad key, for example
        # Everything raised as AITransient is retried by the pipeline's generate node.
        except errors.ServerError as error:
            _log_failure(error)
            if error.code in _RETRIABLE_STATUS:
                raise AITransient() from None
            raise AIUnavailable() from None
        except (httpx.NetworkError, httpx.RemoteProtocolError) as error:
            _log_failure(error)
            raise AITransient() from None
        # Timeouts land here and aren't retried, because each has already taken 45 s.
        # UnknownApiResponseError is a 200 whose body isn't JSON. The SDK raises it as a
        # ValueError rather than an APIError, so it's named on its own. httpx.HTTPError
        # covers every timeout and lost connection.
        except (errors.APIError, errors.UnknownApiResponseError, httpx.HTTPError) as error:
            _log_failure(error)
            raise AIUnavailable() from None
        # Record usage before _check_stop(), because a blocked or cut-off reply can still be billed.
        self._record_usage(response)
        _check_stop(response)
        return response.text

    def _record_usage(self, response) -> None:
        """Add the reply's token counts to the running total."""
        # The SDK can omit the metadata or leave individual counts as None.
        metadata = getattr(response, "usage_metadata", None)
        if metadata is None:
            return
        with self._usage_lock:
            self.usage.input_tokens += metadata.prompt_token_count or 0
            self.usage.output_tokens += (
                (metadata.candidates_token_count or 0) + (metadata.thoughts_token_count or 0)
            )


def _log_failure(error: Exception) -> None:
    """Rule 17: the type and the status, never str(error), which carries the response."""
    logger.warning(
        "ai_provider outcome=error type=%s code=%s status=%s",
        type(error).__name__,
        getattr(error, "code", None),
        getattr(error, "status", None),
    )


# Why a reply stopped, when retrying won't help (A20). Anything else falls through to the text.
_DECLINED_FINISHES = {
    types.FinishReason.SAFETY,
    types.FinishReason.RECITATION,
    types.FinishReason.BLOCKLIST,
    types.FinishReason.PROHIBITED_CONTENT,
    types.FinishReason.SPII,
}


def _check_stop(response) -> None:
    """AIUnavailable with the right message when Gemini blocked the prompt or cut the reply.

    Checked before the text, in this order: a blocked prompt has no candidates at all, and a
    reply cut off for length is also invalid JSON, which would get the wrong message.
    """
    feedback = getattr(response, "prompt_feedback", None)
    if feedback is not None and feedback.block_reason:
        logger.warning("ai_provider outcome=prompt_blocked")
        raise AIUnavailable(DECLINED)
    candidates = getattr(response, "candidates", None) or []
    finish = candidates[0].finish_reason if candidates else None
    if finish == types.FinishReason.MAX_TOKENS:
        logger.warning("ai_provider outcome=cut_off")
        raise AIUnavailable(TOO_MUCH)
    if finish in _DECLINED_FINISHES:
        logger.warning("ai_provider outcome=declined finish_reason=%s", finish.value)
        raise AIUnavailable(DECLINED)


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


def get_judge_provider() -> Provider:
    """The provider for the pipeline's judge node, using AI_JUDGE_MODEL.

    A separate instance keeps the judge's token counts apart from the writer's. Raises
    AIUnavailable(NOT_CONFIGURED) under the same conditions as get_provider().
    """
    config = current_app.config
    if config["AI_PROVIDER"] == "fake":
        return FakeProvider()
    if config["AI_PROVIDER"] == "gemini" and config["GEMINI_API_KEY"]:
        return GeminiProvider(config["GEMINI_API_KEY"], config["AI_JUDGE_MODEL"])
    raise AIUnavailable(NOT_CONFIGURED)
