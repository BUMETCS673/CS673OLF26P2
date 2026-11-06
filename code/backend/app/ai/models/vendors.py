"""The vendors the app can build model clients for. A new vendor is one more entry in VENDORS."""

from collections.abc import Callable
from dataclasses import dataclass

from langchain_core.callbacks import Callbacks
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from langchain_core.rate_limiters import BaseRateLimiter
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from pydantic import SecretStr

from app.ai.fake import FakeChatModel, FakeEmbeddings
from app.ai.models.errors import NOT_CONFIGURED, AIUnavailable
from app.core.settings import EMBEDDING_DIMENSIONS, Settings

FAKE = "fake"  # canned models for tests and local runs with no API key
TIMEOUT_SECONDS = 45  # per call sent to Google as the request deadline

# Takes the model name, role, settings, callbacks and rate limiter.
ChatBuilder = Callable[[str, str, Settings, Callbacks, BaseRateLimiter | None], BaseChatModel]


@dataclass(frozen=True)
class Vendor:
    chat: ChatBuilder
    embeddings: Callable[[str, Settings], Embeddings]  # takes the model name and settings
    is_set_up: Callable[[Settings], bool]  # only a vendor that's set up can be a fallback
    rate_limited: bool  # whether calls wait for a turn from the shared Redis limiter


def _api_key(key: str) -> SecretStr:
    if not key:  # no key means AI is off with a clear message
        raise AIUnavailable(NOT_CONFIGURED)
    return SecretStr(key)  # SecretStr is never printed in logs or reprs


def _fake_chat(
    _name: str, _role: str, _settings: Settings, callbacks: Callbacks, _limiter: object
) -> BaseChatModel:
    return FakeChatModel(callbacks=callbacks)


def _gemini_chat(
    name: str,
    role: str,
    settings: Settings,
    callbacks: Callbacks,
    rate_limiter: BaseRateLimiter | None,
) -> BaseChatModel:
    return ChatGoogleGenerativeAI(
        model=name,
        api_key=_api_key(settings.gemini_api_key),
        # Only Gemini 3 has thinking levels. Older models set thinking with a token budget.
        thinking_level=(
            getattr(settings, f"ai_{role}_thinking") if name.startswith("gemini-3") else None
        ),
        temperature=None,  # the API's default, rather than LangChain's 0.7
        retries=1,  # one attempt: its default of 6 would spend quota on every retry
        timeout=TIMEOUT_SECONDS,
        callbacks=callbacks,
        rate_limiter=rate_limiter,  # waits for a turn first
    )


def _gemini_embeddings(name: str, settings: Settings) -> Embeddings:
    return GoogleGenerativeAIEmbeddings(
        model=name,
        api_key=_api_key(settings.gemini_api_key),
        # a fixed size matching the pgvector column using Matryoshka-style truncation
        output_dimensionality=EMBEDDING_DIMENSIONS,
    )


VENDORS: dict[str, Vendor] = {
    FAKE: Vendor(
        chat=_fake_chat,
        embeddings=lambda _name, _settings: FakeEmbeddings(),
        is_set_up=lambda _settings: False,  # test models are never used as a fallback
        rate_limited=False,
    ),
    "gemini": Vendor(
        chat=_gemini_chat,
        embeddings=_gemini_embeddings,
        is_set_up=lambda settings: bool(settings.gemini_api_key),
        rate_limited=True,
    ),
}


def get_vendor(name: str) -> Vendor:
    if name not in VENDORS:  # a provider setting the app has no client for
        raise AIUnavailable(NOT_CONFIGURED)
    return VENDORS[name]


def is_set_up(name: str, settings: Settings) -> bool:
    vendor = VENDORS.get(name)
    return vendor is not None and vendor.is_set_up(settings)
