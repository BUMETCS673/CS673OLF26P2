"""The errors AI calls raise, and the context manager that turns vendor failures into them."""

import logging
from collections.abc import Iterator
from contextlib import contextmanager

from app.ai.failures import Failure, classify, status_of

logger = logging.getLogger(__name__)

UNAVAILABLE = "The AI service didn't respond. Try again in a minute."
QUOTA_USED_UP = (
    "The AI service is at its limit right now. Wait a minute and try again. "
    "If it still doesn't work, today's limit is used up and resets overnight."
)
NOT_CONFIGURED = "AI generation isn't set up on this server."
AT_CAPACITY = "The AI is at full capacity right now. Try again in a few minutes."


class AIRateLimited(Exception):
    def __init__(self, message: str = QUOTA_USED_UP):
        super().__init__(message)
        self.message = message


class AIUnavailable(Exception):
    def __init__(self, message: str = UNAVAILABLE):
        super().__init__(message)
        self.message = message


class AITransient(AIUnavailable):  # a subclass so callers that catch AIUnavailable get it too
    """A failure that may succeed if retried."""


def _our_error(failure: Failure) -> Exception:
    if failure is Failure.BUSY:  # our own limiter said no so 429 with "at capacity"
        return AIRateLimited(AT_CAPACITY)
    if failure is Failure.RATE_LIMITED:  # Google's quota so 429 with "at its limit"
        return AIRateLimited()
    if failure.retriable:  # overloaded, a server error or a dropped connection
        return AITransient()
    return AIUnavailable()  # bad key, bad request or timeout which retrying won't help


@contextmanager
def ai_errors() -> Iterator[None]:
    """Turn vendor failures into our errors, as `classify` reads them.

    `from None` drops the vendor's error, whose text can carry the learner's content, so no
    traceback can log it later.
    """
    try:
        yield
    except Exception as error:
        failure = classify(error)  # one place decides what every vendor error means
        if failure is None:  # not a vendor error such as a bug so it's re-raised as it is
            raise
        # The error's class and status only, never its text.
        fields: dict[str, str | int] = {
            "failure": failure.value,
            "vendor_error": type(error).__name__,
        }
        if (status := status_of(error)) is not None:
            fields["status"] = status
        logger.warning("ai call failed", extra=fields)
        raise _our_error(failure) from None  # from None drops the vendor's error
