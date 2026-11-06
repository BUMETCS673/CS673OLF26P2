"""Building the chat models and embeddings for each role."""

from collections.abc import Iterator
from contextlib import contextmanager

from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from langchain_core.rate_limiters import BaseRateLimiter
from langchain_core.runnables import RunnableWithFallbacks

from app.ai.failures import FALL_BACK_ON
from app.ai.models.chains import ModelSpec, Role, RunModels, first_models, model_chain
from app.ai.models.vendors import get_vendor
from app.ai.rate_limits import RedisRateLimiter
from app.ai.usage import RoleUsage, RunUsage
from app.core.redis import get_redis
from app.core.settings import Settings

# How long a learner's call waits behind others. A tutor turn makes at most 4 chat calls and 2
# searches, so with the timeout above it stays under nginx's limit of 280 seconds.
LEARNER_MAX_WAIT_MS = 12_000

# A model with fallbacks, as load_chat_model returns when the role has later models.
ChatModel = BaseChatModel | RunnableWithFallbacks


def _rate_limiter(
    model: str, settings: Settings, max_wait_ms: int | None = None
) -> RedisRateLimiter | None:
    per_minute = settings.model_rate_limit(model)  # a little under Google's per-minute quota
    # shared through Redis so every process draws from one count per model
    return RedisRateLimiter(get_redis(), model, per_minute, max_wait_ms) if per_minute else None


def _build_chat(
    role: Role, spec: ModelSpec, settings: Settings, usage: RunUsage | None, learner_waiting: bool
) -> BaseChatModel:
    # one usage handler per model so a fallback's calls count against its own budget
    callbacks = [usage.for_role(role, spec.name)] if usage else None
    vendor = get_vendor(spec.vendor)  # AIUnavailable for a provider with no client
    max_wait = LEARNER_MAX_WAIT_MS if learner_waiting else None  # None lets background jobs wait
    limiter = _rate_limiter(spec.name, settings, max_wait) if vendor.rate_limited else None
    return vendor.chat(spec.name, role, settings, callbacks, limiter)


def load_chat_model(
    role: Role,
    settings: Settings,
    usage: RunUsage | None = None,
    *,
    learner_waiting: bool = False,
    models: RunModels | None = None,
) -> ChatModel:
    """The chat model for `role`. Raises AIUnavailable if it isn't set up.

    With `usage`, every call this model makes is counted there. With `learner_waiting`, a call
    refuses with AIRateLimited rather than wait behind a long queue, so use it inside ai_errors.
    `models` is the run's plan, from BudgetService or `first_models`. Without it, the role's
    whole chain is used, which a judge can't do, since its chain depends on what it checks.
    The role's later models take over a call that one model can't answer, as FALL_BACK_ON says.
    """
    # Step 1: the run's chain for this role or the role's whole chain
    if models is None:
        if role == Role.JUDGE:  # a judge's chain depends on what it checks
            raise ValueError("A judge needs the run's models.")
        models = first_models(settings, [role])
    first, *later = models.chain(role)
    # Step 2: build the first model and the rest as LangChain fallbacks
    model = _build_chat(role, first, settings, usage, learner_waiting)
    if not later:
        return model
    return model.with_fallbacks(  # RunnableWithFallbacks tries each model in order on failure
        [_build_chat(role, fallback, settings, usage, learner_waiting) for fallback in later],
        exceptions_to_handle=FALL_BACK_ON,  # only failures about this model not bad requests
    )


def load_embeddings(
    settings: Settings, usage: RunUsage | None = None, *, learner_waiting: bool = False
) -> Embeddings:
    """The embedding model. Raises AIUnavailable if it isn't set up.

    `learner_waiting` works as it does in `load_chat_model`.
    """
    # Step 1: build the vendor's embedding client
    spec = model_chain(Role.EMBEDDER, settings)[0]  # the first model as model_name reads it
    vendor = get_vendor(spec.vendor)
    embeddings = vendor.embeddings(spec.name, settings)
    # Step 2: wrap it with the rate limiter and usage counting if either applies
    max_wait = LEARNER_MAX_WAIT_MS if learner_waiting else None
    limiter = _rate_limiter(spec.name, settings, max_wait) if vendor.rate_limited else None
    role_usage = usage.for_role(Role.EMBEDDER, spec.name) if usage else None
    if limiter is None and role_usage is None:  # skip the wrapper when there's nothing to add
        return embeddings
    return GuardedEmbeddings(embeddings, limiter, role_usage)


class GuardedEmbeddings(Embeddings):
    """Takes a rate-limiter turn and counts each call, since embeddings have no such settings.

    A refused call is refunded, as RoleUsage does for chat models.
    """

    def __init__(
        self, embeddings: Embeddings, limiter: BaseRateLimiter | None, usage: RoleUsage | None
    ):
        self.embeddings = embeddings
        self.limiter = limiter
        self.usage = usage

    @contextmanager
    def _counted(self) -> Iterator[None]:
        if self.usage:
            self.usage.count_call()  # counted before the call since a timeout may still cost quota
        try:
            yield
        except Exception as error:
            if self.usage:
                self.usage.record_error(error)  # refunds it if the vendor refused it
            raise  # re-raised unchanged for ai_errors to classify
        if self.usage:
            self.usage.record_success()  # embeddings report no tokens so the counts are 0

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        with self._counted():
            return self.embeddings.embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        with self._counted():
            return self.embeddings.embed_query(text)

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        # The turn comes first, so a ModelBusy refusal is never counted.
        if self.limiter:
            await self.limiter.aacquire()  # may wait in Redis or raise ModelBusy
        with self._counted():
            return await self.embeddings.aembed_documents(texts)  # the whole list in one request

    async def aembed_query(self, text: str) -> list[float]:
        if self.limiter:
            await self.limiter.aacquire()
        with self._counted():
            return await self.embeddings.aembed_query(text)
