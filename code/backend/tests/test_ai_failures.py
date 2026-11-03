"""What each vendor failure means, and that the fallback types agree with it."""

import httpx
import pytest
from google.genai import errors
from langchain_google_genai._common import GoogleGenerativeAIError
from langchain_google_genai.chat_models import (
    ChatGoogleGenerativeAIError,
    GoogleAPIError,
    GoogleRateLimitError,
)

from app.ai.failures import FALL_BACK_ON, Failure, classify
from app.ai.rate_limits import ModelBusy


def _api_error(kind, code):
    return kind(code, {"error": {"code": code, "message": "x", "status": "X"}})


def _wrapped(cause):
    error = GoogleGenerativeAIError("failed")
    error.__cause__ = cause
    return error


@pytest.mark.parametrize(
    ("error", "failure"),
    [
        (ModelBusy(), Failure.BUSY),
        (GoogleRateLimitError("slow down"), Failure.RATE_LIMITED),
        (_api_error(errors.ClientError, 429), Failure.RATE_LIMITED),
        (_api_error(GoogleAPIError, 503), Failure.OVERLOADED),
        (_api_error(errors.ServerError, 500), Failure.SERVER_ERROR),
        (_api_error(errors.ServerError, 504), Failure.SERVER_ERROR),
        (_api_error(errors.ClientError, 408), Failure.TRANSIENT),
        (_api_error(errors.ClientError, 400), Failure.PERMANENT),
        (_api_error(errors.ServerError, 501), Failure.PERMANENT),
        (_wrapped(_api_error(errors.ServerError, 503)), Failure.OVERLOADED),
        (_wrapped(None), Failure.PERMANENT),
        (ChatGoogleGenerativeAIError("bad key"), Failure.PERMANENT),
        (httpx.ConnectError("offline"), Failure.TRANSIENT),
        (httpx.ReadTimeout("slow"), Failure.PERMANENT),
        (ValueError(), None),
    ],
)
def test_each_failure_is_classified(error, failure):
    assert classify(error) is failure


def test_only_a_refusal_spends_nothing():
    assert {failure for failure in Failure if failure.refused} == {
        Failure.BUSY,
        Failure.RATE_LIMITED,
        Failure.OVERLOADED,
    }


# What a chat model raises, since only chat models take LangChain's fallbacks.
CHAT_ERRORS = [
    ModelBusy(),
    GoogleRateLimitError("slow down"),
    _api_error(GoogleAPIError, 503),
    _api_error(GoogleAPIError, 500),
    _api_error(GoogleAPIError, 504),
    ChatGoogleGenerativeAIError("bad request"),
    httpx.ConnectError("offline"),
    httpx.ReadTimeout("slow"),
]


@pytest.mark.parametrize("error", CHAT_ERRORS)
def test_the_fallback_types_cover_exactly_the_failures_that_fall_back(error):
    assert isinstance(error, FALL_BACK_ON) is classify(error).falls_back
