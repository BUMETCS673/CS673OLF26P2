"""Google's Gemini, on the free tier (A1). Billing is never turned on (A2).

All google.genai usage is confined to this module.
"""

import logging

import httpx
from google import genai
from google.genai import errors, types

from app.ai.provider import (
    DECLINED,
    TOO_MUCH,
    AIRateLimited,
    AITransient,
    AIUnavailable,
    Prompt,
    Provider,
)

logger = logging.getLogger(__name__)

# Excludes 501 and 504, which need a changed request or deadline, and 429, which a retry within
# seconds can't clear.
_RETRIABLE_STATUS = frozenset({408, 500, 502, 503})


class GeminiProvider(Provider):
    def __init__(self, api_key: str, model: str, client=None, thinking: str = "low"):
        super().__init__(model)
        try:
            self._thinking = types.ThinkingLevel[thinking.upper()]
        except KeyError:
            raise ValueError(f"unknown thinking level: {thinking!r}") from None
        # `client` lets tests pass a fake. The SDK's timeout is in milliseconds: six sequential
        # calls at 45 s stay under nginx's 280 s, so a slow reply ends as our 503, not nginx's 504.
        if client is None:
            client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=45_000))
        self._client = client

    def _complete(self, prompt: Prompt, schema: dict) -> str | None:
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
            # A20: Gemini 3 models default to high thinking, which is slower, so each role sets
            # its own level. Never send thinking_budget as well: the two together are a 400.
            thinking_config=types.ThinkingConfig(thinking_level=self._thinking),
        )
        # One attempt: the SDK doesn't retry unless asked to, and a retry would spend the
        # free quota twice. Only the pipeline's generate node retries, on AITransient. `from None`
        # drops the SDK error, whose text carries Google's response body, so no traceback can log
        # it later (rule 17).
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
        # Before _check_stop(), which raises on a blocked or cut-off reply.
        self._record_usage(response)
        _check_stop(response)
        return response.text

    def _record_usage(self, response) -> None:
        # The SDK can omit the metadata or leave individual counts as None.
        metadata = getattr(response, "usage_metadata", None)
        if metadata is None:
            return
        self._add_usage(
            metadata.prompt_token_count or 0,
            (metadata.candidates_token_count or 0) + (metadata.thoughts_token_count or 0),
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
