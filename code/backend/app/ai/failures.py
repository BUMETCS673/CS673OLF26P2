"""What a failed model call means, decided in one place.

Falling back, refunding a call, retrying, and the error a learner sees all read `classify`, so
they can't disagree about a vendor's error.
"""

from enum import Enum

import httpx
from google.genai import errors
from langchain_google_genai._common import GoogleGenerativeAIError
from langchain_google_genai.chat_models import GoogleAPIError, GoogleRateLimitError

from app.ai.rate_limits import ModelBusy

RATE_LIMITED_STATUS = 429
OVERLOADED_STATUS = 503
SERVER_RETRIABLE_STATUS = frozenset({500, 502, 504})
CLIENT_RETRIABLE_STATUS = frozenset({408})


class Failure(Enum):
    """Why a call failed, which says what can still be done about it."""

    BUSY = "busy"  # our own limiter refused, before the call went out
    RATE_LIMITED = "rate_limited"  # the vendor refused this model's quota
    OVERLOADED = "overloaded"  # the vendor refused, since this model is in high demand
    SERVER_ERROR = "server_error"  # this model failed on the vendor's side
    TRANSIENT = "transient"  # the connection failed, so the same call may still work
    PERMANENT = "permanent"  # a bad key, a bad request, or a timeout

    @property
    def refused(self) -> bool:
        """Turned away before the model ran, so the call spent nothing."""
        return self in {Failure.BUSY, Failure.RATE_LIMITED, Failure.OVERLOADED}

    @property
    def falls_back(self) -> bool:
        """About this model only, so the next model in the chain may still answer."""
        return self.refused or self is Failure.SERVER_ERROR

    @property
    def retriable(self) -> bool:
        """Worth trying again later on the same chain."""
        return self in {Failure.OVERLOADED, Failure.SERVER_ERROR, Failure.TRANSIENT}


def status_of(error: BaseException) -> int | None:
    """The HTTP status a vendor's error carries, if any."""
    if isinstance(error, errors.APIError):
        return error.code
    # Embeddings wrap the SDK's error, so its status is on the cause.
    if isinstance(error, GoogleGenerativeAIError):
        return getattr(error.__cause__, "code", None)
    return None


def _from_status(status: int) -> Failure:
    if status == RATE_LIMITED_STATUS:
        return Failure.RATE_LIMITED
    if status == OVERLOADED_STATUS:
        return Failure.OVERLOADED
    if status in SERVER_RETRIABLE_STATUS:
        return Failure.SERVER_ERROR
    if status in CLIENT_RETRIABLE_STATUS:
        return Failure.TRANSIENT
    return Failure.PERMANENT


def classify(error: BaseException) -> Failure | None:
    """What a vendor's or our limiter's error means. None for an error that isn't theirs."""
    if isinstance(error, ModelBusy):
        return Failure.BUSY
    if isinstance(error, GoogleRateLimitError):
        return Failure.RATE_LIMITED
    status = status_of(error)
    if status is not None:
        return _from_status(status)
    if isinstance(error, GoogleGenerativeAIError):
        return Failure.PERMANENT
    if isinstance(error, httpx.NetworkError | httpx.RemoteProtocolError):
        return Failure.TRANSIENT
    if isinstance(error, httpx.HTTPError):
        return Failure.PERMANENT
    return None


# LangChain's fallbacks take exception types, not a check. A chat model raises these for our
# limiter, a 429, and any 5xx, so every failure that falls back is covered. A 501 falls back
# too, which does no harm, since the next model may support the request. A test keeps them in
# step with `Failure.falls_back`.
FALL_BACK_ON = (ModelBusy, GoogleRateLimitError, GoogleAPIError)
