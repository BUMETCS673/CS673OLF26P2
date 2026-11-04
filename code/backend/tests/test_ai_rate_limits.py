"""The rate limiter that all workers share through Redis."""

import asyncio

import httpx
import pytest
from langchain_core.embeddings import Embeddings
from langchain_google_genai.chat_models import GoogleAPIError, GoogleRateLimitError
from redis.exceptions import ConnectionError as RedisConnectionError

from app.ai import rate_limits
from app.ai.models import (
    AT_CAPACITY,
    AIRateLimited,
    GuardedEmbeddings,
    Role,
    ai_errors,
    load_chat_model,
    load_embeddings,
)
from app.ai.rate_limits import ModelBusy, RedisRateLimiter
from app.ai.usage import RoleUsage
from app.core.redis import get_redis
from app.core.settings import Settings


@pytest.fixture
async def limiter():
    """Ten calls a second, on a key of its own."""
    await get_redis().delete("rate:test-model", "rate:other-model")
    yield RedisRateLimiter(get_redis(), "test-model", 600)
    await get_redis().delete("rate:test-model", "rate:other-model")


@pytest.fixture
def waits(monkeypatch):
    """Records each wait, instead of waiting."""
    recorded = []

    async def record(seconds):
        recorded.append(seconds)

    monkeypatch.setattr(rate_limits.asyncio, "sleep", record)
    return recorded


async def test_the_first_call_goes_straight_through(limiter, waits):
    assert await limiter.aacquire() is True
    assert waits == []


async def test_the_next_call_waits_its_turn(limiter, waits):
    await limiter.aacquire()
    await limiter.aacquire()

    assert len(waits) == 1
    assert 0 < waits[0] <= 0.1


async def test_callers_at_once_each_get_a_different_turn(limiter, waits):
    await asyncio.gather(*(limiter.aacquire() for _ in range(4)))

    assert len(waits) == 3
    assert len(set(waits)) == 3
    assert max(waits) <= 0.3


async def test_two_limiters_on_one_model_share_its_turns(limiter, waits):
    await limiter.aacquire()
    await RedisRateLimiter(get_redis(), "test-model", 600).aacquire()

    assert len(waits) == 1


async def test_models_dont_affect_each_other(limiter, waits):
    await limiter.aacquire()
    await RedisRateLimiter(get_redis(), "other-model", 600).aacquire()

    assert waits == []


async def test_a_long_queue_refuses_without_taking_a_turn(limiter, waits):
    impatient = RedisRateLimiter(get_redis(), "test-model", 600, max_wait_ms=50)
    await limiter.aacquire()  # the next turn is now about 100 ms away

    with pytest.raises(ModelBusy):
        await impatient.aacquire()
    assert waits == []
    assert await limiter.aacquire() is True
    assert len(waits) == 1 and waits[0] <= 0.1  # no turn was added by the refusal


def _google_error(kind, code):
    return kind(code, {"error": {"code": code, "message": "x", "status": "X"}})


@pytest.mark.parametrize(
    ("error", "spent"),
    [
        (ModelBusy(), 0),
        (_google_error(GoogleRateLimitError, 429), 0),
        (_google_error(GoogleAPIError, 503), 0),
        (_google_error(GoogleAPIError, 500), 1),
        (httpx.ReadTimeout("slow"), 1),
        (ValueError(), 1),
    ],
)
def test_only_a_refused_call_spends_nothing(error, spent):
    usage = RoleUsage("writer", "test-model")
    usage.on_chat_model_start()
    usage.on_llm_error(error)
    assert usage.calls == spent


def test_being_refused_becomes_a_message_for_the_learner():
    def says_at_capacity(error):
        return error.message == AT_CAPACITY

    with pytest.raises(AIRateLimited, check=says_at_capacity), ai_errors():
        raise ModelBusy()


async def test_not_blocking_says_no_without_taking_a_turn(limiter, waits):
    assert await limiter.aacquire(blocking=False) is True
    assert await limiter.aacquire(blocking=False) is False
    assert waits == []


async def test_calls_go_ahead_if_redis_is_down(waits):
    class _Down:
        def register_script(self, _script):
            async def run(**_):
                raise RedisConnectionError

            return run

    assert await RedisRateLimiter(_Down(), "test-model", 60).aacquire() is True
    assert waits == []


class _Recording(Embeddings):
    def __init__(self, events):
        self.events = events

    def embed_documents(self, texts):
        return [[0.0] for _ in texts]

    def embed_query(self, text):
        return [0.0]

    async def aembed_documents(self, texts):
        self.events.append("embed")
        return [[0.0] for _ in texts]

    async def aembed_query(self, text):
        self.events.append("embed")
        return [0.0]


async def test_embeddings_wait_their_turn_before_calling():
    events = []

    class _Limiter:
        async def aacquire(self):
            events.append("turn")

    embeddings = GuardedEmbeddings(_Recording(events), _Limiter(), None)

    await embeddings.aembed_documents(["a"])
    await embeddings.aembed_query("b")

    assert events == ["turn", "embed", "turn", "embed"]


def _settings(limits, default=0):
    return Settings(
        ai_writer_provider="gemini",
        ai_embedder_provider="gemini",
        ai_writer_model="writer-model",
        ai_embedder_model="embedder-model",
        gemini_api_key="not-a-real-key",
        ai_model_rate_limit=default,
        ai_model_rate_limits=limits,
    )


def test_a_chat_model_with_a_limit_gets_a_limiter():
    model = load_chat_model(Role.WRITER, _settings("writer-model:30"))

    assert isinstance(model.rate_limiter, RedisRateLimiter)
    assert model.rate_limiter.key == "rate:writer-model"
    assert model.rate_limiter.gap_ms == 2000


def test_embeddings_with_a_limit_are_wrapped():
    embeddings = load_embeddings(_settings("embedder-model:30"))

    assert isinstance(embeddings.limiter, RedisRateLimiter)


def test_a_model_with_no_limit_gets_no_limiter():
    assert load_chat_model(Role.WRITER, _settings("")).rate_limiter is None
    assert not isinstance(load_embeddings(_settings("")), GuardedEmbeddings)


def test_other_models_use_the_default_limit():
    model = load_chat_model(Role.WRITER, _settings("", default=60))

    assert model.rate_limiter.gap_ms == 1000


def test_fake_models_arent_limited():
    settings = Settings(ai_writer_provider="fake", ai_embedder_provider="fake")

    assert load_chat_model(Role.WRITER, settings).rate_limiter is None
    assert not isinstance(load_embeddings(settings), GuardedEmbeddings)
