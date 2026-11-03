"""Chat models and embeddings for each role, and the errors they can raise."""

from collections.abc import Iterator
from contextlib import contextmanager
from enum import StrEnum

import httpx
from google.genai import errors
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain_google_genai._common import GoogleGenerativeAIError
from langchain_google_genai.chat_models import GoogleRateLimitError
from pydantic import SecretStr

from app.ai.fake import FakeChatModel, FakeEmbeddings
from app.ai.rate_limits import ModelBusy, RateLimitedEmbeddings, RedisRateLimiter
from app.ai.usage import CountedEmbeddings, RunUsage
from app.core.redis import get_redis
from app.core.settings import EMBEDDING_DIMENSIONS, Settings

TIMEOUT_SECONDS = 45
# How long a learner's call waits behind others. A tutor turn makes at most 4 chat calls and 2
# searches, so with the timeout above it stays under nginx's limit of 280 seconds.
LEARNER_MAX_WAIT_MS = 12_000
RETRIABLE_STATUS = frozenset({408, 500, 502, 503})

UNAVAILABLE = "The AI service didn't respond. Try again in a minute."
QUOTA_USED_UP = (
    "The AI service is at its limit right now. Wait a minute and try again. "
    "If it still doesn't work, today's limit is used up and resets overnight."
)
NOT_CONFIGURED = "AI generation isn't set up on this server."
AT_CAPACITY = "The AI is at full capacity right now. Try again in a few minutes."


class Role(StrEnum):
    """What a model is used for. Each role has its own settings."""

    WRITER = "writer"
    JUDGE = "judge"
    EMBEDDER = "embedder"


class AIRateLimited(Exception):
    def __init__(self, message: str = QUOTA_USED_UP):
        super().__init__(message)
        self.message = message


class AIUnavailable(Exception):
    def __init__(self, message: str = UNAVAILABLE):
        super().__init__(message)
        self.message = message


class AITransient(AIUnavailable):
    """A failure that may succeed if retried."""


def _vendor_and_model(role: Role, settings: Settings) -> tuple[str, str]:
    return (
        getattr(settings, f"ai_{role}_provider"),
        getattr(settings, f"ai_{role}_model"),
    )


def _api_key(settings: Settings) -> SecretStr:
    if not settings.gemini_api_key:
        raise AIUnavailable(NOT_CONFIGURED)
    return SecretStr(settings.gemini_api_key)


def model_name(role: Role, settings: Settings) -> str:
    """The name usage is recorded under, without building a client."""
    vendor, model = _vendor_and_model(role, settings)
    return "fake" if vendor == "fake" else model


def _rate_limiter(
    model: str, settings: Settings, max_wait_ms: int | None = None
) -> RedisRateLimiter | None:
    per_minute = settings.model_rate_limit(model)
    return RedisRateLimiter(get_redis(), model, per_minute, max_wait_ms) if per_minute else None


def load_chat_model(
    role: Role,
    settings: Settings,
    usage: RunUsage | None = None,
    *,
    learner_waiting: bool = False,
) -> BaseChatModel:
    """The chat model for `role`. Raises AIUnavailable if it isn't set up.

    With `usage`, every call this model makes is counted there. With `learner_waiting`, a call
    refuses with AIRateLimited rather than wait behind a long queue, so use it inside ai_errors.
    """
    vendor, model = _vendor_and_model(role, settings)
    callbacks = [usage.for_role(role, model_name(role, settings))] if usage else None
    if vendor == "fake":
        return FakeChatModel(callbacks=callbacks)
    if vendor != "gemini":
        raise AIUnavailable(NOT_CONFIGURED)
    return ChatGoogleGenerativeAI(
        model=model,
        api_key=_api_key(settings),
        thinking_level=getattr(settings, f"ai_{role}_thinking"),
        temperature=None,  # the API's default, rather than LangChain's 0.7
        retries=1,  # one attempt: its default of 6 would spend quota on every retry
        timeout=TIMEOUT_SECONDS,
        callbacks=callbacks,
        rate_limiter=_rate_limiter(
            model, settings, LEARNER_MAX_WAIT_MS if learner_waiting else None
        ),
    )


def load_embeddings(
    settings: Settings, usage: RunUsage | None = None, *, learner_waiting: bool = False
) -> Embeddings:
    """The embedding model. Raises AIUnavailable if it isn't set up.

    `learner_waiting` works as it does in `load_chat_model`.
    """
    vendor, model = _vendor_and_model(Role.EMBEDDER, settings)
    if vendor == "fake":
        embeddings = FakeEmbeddings()
    elif vendor == "gemini":
        embeddings = GoogleGenerativeAIEmbeddings(
            model=model, api_key=_api_key(settings), output_dimensionality=EMBEDDING_DIMENSIONS
        )
        max_wait = LEARNER_MAX_WAIT_MS if learner_waiting else None
        if limiter := _rate_limiter(model, settings, max_wait):
            embeddings = RateLimitedEmbeddings(embeddings, limiter)
    else:
        raise AIUnavailable(NOT_CONFIGURED)
    if usage is None:
        return embeddings
    role_usage = usage.for_role(Role.EMBEDDER, model_name(Role.EMBEDDER, settings))
    return CountedEmbeddings(embeddings, role_usage)


@contextmanager
def ai_errors() -> Iterator[None]:
    """Turn vendor failures into our errors.

    `from None` drops the vendor's error, whose text can carry the learner's content, so no
    traceback can log it later.
    """
    try:
        yield
    except ModelBusy:
        raise AIRateLimited(AT_CAPACITY) from None
    except GoogleRateLimitError:
        raise AIRateLimited() from None
    except GoogleGenerativeAIError as error:
        # Embeddings wrap the SDK's error, so its status is on the cause.
        if getattr(error.__cause__, "code", None) == 429:
            raise AIRateLimited() from None
        raise AIUnavailable() from None
    except errors.ClientError as error:
        if error.code == 429:
            raise AIRateLimited() from None
        if error.code in RETRIABLE_STATUS:
            raise AITransient() from None
        raise AIUnavailable() from None
    except errors.ServerError as error:
        if error.code in RETRIABLE_STATUS:
            raise AITransient() from None
        raise AIUnavailable() from None
    except (httpx.NetworkError, httpx.RemoteProtocolError):
        raise AITransient() from None
    except (errors.APIError, httpx.HTTPError):
        raise AIUnavailable() from None
