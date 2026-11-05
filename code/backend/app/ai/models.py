"""Chat models and embeddings for each role, and the errors they can raise."""

import logging
from collections.abc import Awaitable, Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain.agents.structured_output import StructuredOutputError
from langchain_core.embeddings import Embeddings
from langchain_core.exceptions import OutputParserException
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.rate_limiters import BaseRateLimiter
from langchain_core.runnables import Runnable, RunnableWithFallbacks
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from pydantic import BaseModel, SecretStr, ValidationError

from app.ai.failures import FALL_BACK_ON, Failure, classify, status_of
from app.ai.fake import FakeChatModel, FakeEmbeddings
from app.ai.rate_limits import RedisRateLimiter
from app.ai.usage import RoleUsage, RunUsage
from app.core.redis import get_redis
from app.core.settings import EMBEDDING_DIMENSIONS, Settings

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 45  # per call sent to Google as the request deadline
# How long a learner's call waits behind others. A tutor turn makes at most 4 chat calls and 2
# searches, so with the timeout above it stays under nginx's limit of 280 seconds.
LEARNER_MAX_WAIT_MS = 12_000
# Replies that don't fit the requested shape.
BAD_REPLY = (OutputParserException, ValidationError, StructuredOutputError)

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
    HELPER = "helper"  # the high-volume calls, on a model with a larger quota
    EMBEDDER = "embedder"


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


# A model with fallbacks, as load_chat_model returns when the role has later models.
ChatModel = BaseChatModel | RunnableWithFallbacks


def _structured(model: BaseChatModel, schema: type[BaseModel]) -> Runnable:
    # Google documents tool calls for Gemma on the Gemini API, but not its JSON schema output, so
    # Gemma returns the reply as a tool call. Gemini models use their schema output.
    if isinstance(model, ChatGoogleGenerativeAI) and "gemma-" in model.model:
        return model.with_structured_output(schema, method="function_calling")  # via a tool call
    return model.with_structured_output(schema)  # Gemini's native JSON schema mode


def _with_schema(model: ChatModel, schema: type[BaseModel]) -> Runnable:
    """Structured output on the model and on each of its fallbacks."""
    if isinstance(model, RunnableWithFallbacks):
        # rebuilt since the schema wraps each model and each may need a different method
        return _structured(model.runnable, schema).with_fallbacks(
            [_structured(fallback, schema) for fallback in model.fallbacks],
            exceptions_to_handle=model.exceptions_to_handle,  # the same failures fall back
        )
    return _structured(model, schema)  # a single model no chain


class ChainFallbackMiddleware(AgentMiddleware):
    """An agent's fallbacks, tried only for the failures `with_fallbacks` handles too.

    LangChain's ModelFallbackMiddleware falls back on any error, so a bad request would be
    sent, and counted, once for every model in the chain.
    """

    def __init__(self, models: Sequence[BaseChatModel]):
        super().__init__()
        self.models = list(models)  # the fallbacks in chain order

    async def awrap_model_call(
        self, request: ModelRequest, handler: Callable[[ModelRequest], Awaitable[ModelResponse]]
    ) -> ModelResponse:
        # Step 1: try the agent's own model
        try:
            return await handler(request)
        # only our limiter, 429s and 5xx fall back anything else raises
        except FALL_BACK_ON as error:
            last = error
        # Step 2: try each fallback in turn with the same request
        for model in self.models:
            try:
                return await handler(request.override(model=model))  # same messages and tools
            except FALL_BACK_ON as error:
                last = error
        # Step 3: every model failed so raise the last error
        raise last  # ai_errors turns it into ours


def agent_model(model: ChatModel) -> tuple[BaseChatModel, list[AgentMiddleware]]:
    """An agent takes the first model itself, and its fallbacks as middleware."""
    if isinstance(model, RunnableWithFallbacks):
        # create_agent needs a plain model so the chain moves into middleware
        return model.runnable, [ChainFallbackMiddleware(model.fallbacks)]
    return model, []  # no fallbacks means no middleware


async def structured_reply[T: BaseModel](
    model: ChatModel, schema: type[T], messages: Sequence[BaseMessage]
) -> T | None:
    """Returns the model's reply as `schema`, and raises AIUnavailable for a malformed reply."""
    # Step 1: call the model and its fallbacks in turn asking for `schema`
    try:
        with ai_errors():  # vendor errors become ours each failure logged by kind and status
            # Gemini uses its JSON schema mode and Gemma a tool call on every model in the chain
            return await _with_schema(model, schema).ainvoke(messages)
    # Step 2: a reply that doesn't fit the schema counts as the service being unavailable
    except BAD_REPLY:  # parse or validation errors from LangChain or Pydantic
        logger.info("ai reply rejected", extra={"schema": schema.__name__})
        raise AIUnavailable() from None  # the caller shows its "didn't respond" message


async def structured_reply_or_none[T: BaseModel](
    model: ChatModel,
    schema: type[T],
    messages: Sequence[BaseMessage],
    label: str,
    *,
    raise_transient: bool = False,
) -> T | None:
    """Returns None instead of raising, except AITransient when a graph node retries it."""
    try:
        return await structured_reply(model, schema, messages)
    except (AIRateLimited, AIUnavailable) as error:
        # let LangGraph's RetryPolicy retry the node on a temporary failure
        if raise_transient and isinstance(error, AITransient):
            raise
        logger.warning("%s outcome=failed type=%s", label, type(error).__name__)
        return None  # the caller treats None as "no answer" and carries on


def _vendor_and_model(role: Role, settings: Settings) -> tuple[str, str]:
    return (  # one pair of settings per role like ai_writer_provider and ai_writer_model
        getattr(settings, f"ai_{role}_provider"),
        getattr(settings, f"ai_{role}_model"),
    )


def _api_key(key: str) -> SecretStr:
    if not key:  # no key means AI is off with a clear message
        raise AIUnavailable(NOT_CONFIGURED)
    return SecretStr(key)  # SecretStr is never printed in logs or reprs


@dataclass(frozen=True)  # frozen makes specs hashable for sets and dict keys
class ModelSpec:
    vendor: str
    name: str


def model_chain(role: Role, settings: Settings) -> list[ModelSpec]:
    """The role's models in order of preference, starting with its own setting.

    The judge's chain is also the strength order: strongest first, and listing every model
    whose cards it checks. `check_model_chains` makes sure of that at startup.
    """
    vendor, model = _vendor_and_model(role, settings)
    if vendor == "fake":  # one canned model for tests and local runs with no chain
        return [ModelSpec("fake", "fake")]
    first = ModelSpec(vendor, model)
    fallbacks = getattr(settings, f"ai_{role}_fallbacks", "")  # "vendor:modelvendor:model"
    # split on the first ":" only so a model name may contain one
    rest = [ModelSpec(*item.strip().split(":", 1)) for item in fallbacks.split(",") if item.strip()]
    # A fallback that isn't set up is skipped, so a full model reads as a limit.
    return [first, *(spec for spec in rest if spec != first and _is_set_up(spec, settings))]


JUDGED_ROLES = (Role.WRITER, Role.HELPER)  # the roles whose cards a judge checks


def judge_chain(settings: Settings, checked: Sequence[ModelSpec]) -> list[ModelSpec]:
    """The judge's models ranked above every one in `checked`, so it's always the stronger.

    A model the judge's chain doesn't rank is left out of the cut. That only happens when AI
    isn't set up, since `check_model_chains` refuses such a chain at startup.
    """
    chain = model_chain(Role.JUDGE, settings)
    if chain[0].vendor == "fake":
        return chain
    ranks = [chain.index(spec) for spec in checked if spec in chain]  # each checked model's rank
    # cut above the strongest checked model so every judge left outranks them all
    return chain[: min(ranks)] if ranks else chain


def check_model_chains(settings: Settings) -> None:
    """Refuses to start with a judge that can't be ranked above each model it checks."""
    judge = model_chain(Role.JUDGE, settings)
    if not _is_set_up(judge[0], settings):  # AI is off so there's nothing to check
        return
    for role in JUDGED_ROLES:
        for spec in model_chain(role, settings):
            # the judge's first model must outrank them so it can't be one of them
            if _is_set_up(spec, settings) and spec not in judge[1:]:
                raise ValueError(  # fails the worker's startup catching a config error early
                    f"The judge's chain must list {spec.name}, the {role} model, after its "
                    "first model, so the judge can be ranked above it."
                )


@dataclass(frozen=True)
class RunModels:
    """The models each role may use in one run, in the order it tries them.

    Budgeting and loading both read this, so they can't disagree about a role's models.
    """

    chains: Mapping[Role, tuple[ModelSpec, ...]]

    def chain(self, role: Role) -> tuple[ModelSpec, ...]:
        return self.chains[role]

    def first(self, role: Role) -> ModelSpec:
        return self.chains[role][0]


# Where a role starts in `chain`, given the other roles' picks so far, or None if no model has
# room. It must not change anything, since the planner can try a role more than once.
StartPicker = Callable[[Role, Sequence[ModelSpec], Mapping[Role, ModelSpec]], ModelSpec | None]


def _first_model(
    _role: Role, chain: Sequence[ModelSpec], _picked: Mapping[Role, ModelSpec]
) -> ModelSpec | None:
    return chain[0] if chain else None


def plan_models(
    settings: Settings,
    roles: Iterable[Role],
    *,
    judged: Role | None = None,
    start: StartPicker = _first_model,
) -> RunModels | None:
    """Each role's models for one run: from the model `start` picks, down its chain.

    The judge plans last, from only the models above every one `judged` may use. If none of
    those has room, `judged` starts one model weaker and the judge tries again, since a weaker
    model's cards leave more judges ranked above them. None means some role had no model left.
    """
    roles = list(roles)  # iterated more than once below
    has_judge = Role.JUDGE in roles
    if has_judge and judged not in roles:  # a programming error not a runtime condition
        raise ValueError("A run with a judge must say which role's cards it checks.")
    picked: dict[Role, ModelSpec] = {}  # each role's starting model so far
    chains: dict[Role, tuple[ModelSpec, ...]] = {}

    def take(role: Role, chain: Sequence[ModelSpec]) -> bool:
        spec = start(role, chain, picked)  # e.g the first model with budget room
        if spec is None:
            return False
        picked[role] = spec
        # from the pick down which gives its fallbacks
        chains[role] = tuple(chain[chain.index(spec) :])
        return True

    # Step 1: every role other than the judge and the one it checks picks independently
    for role in roles:
        if role not in (Role.JUDGE, judged) and not take(role, model_chain(role, settings)):
            return None  # a role with no room means the run can't go ahead
    if judged is None or judged not in roles:
        return RunModels(chains)
    # Step 2: pick the checked role and a judge above it weakening the checked role until
    # a judge fits
    checked = model_chain(judged, settings)
    while take(judged, checked):
        if not has_judge or take(Role.JUDGE, judge_chain(settings, chains[judged])):
            return RunModels(chains)
        checked = checked[checked.index(picked[judged]) + 1 :]  # skip past this pick
    return None  # ran out of checked models


def first_models(
    settings: Settings, roles: Iterable[Role], *, judged: Role | None = None
) -> RunModels:
    """Each role's whole chain, for a run that goes ahead without checking budgets."""
    models = plan_models(settings, roles, judged=judged)  # start defaults to each chain's first
    if models is None:  # only a judge with no model above the one it checks
        raise AIUnavailable(NOT_CONFIGURED)
    return models


def model_name(role: Role, settings: Settings) -> str:
    """The name the role's first model is recorded under, without building a client."""
    return model_chain(role, settings)[0].name


def _rate_limiter(
    model: str, settings: Settings, max_wait_ms: int | None = None
) -> RedisRateLimiter | None:
    per_minute = settings.model_rate_limit(model)  # a little under Google's per-minute quota
    # shared through Redis so every process draws from one count per model
    return RedisRateLimiter(get_redis(), model, per_minute, max_wait_ms) if per_minute else None


def _is_set_up(spec: ModelSpec, settings: Settings) -> bool:
    return spec.vendor == "gemini" and bool(settings.gemini_api_key)  # the only real vendor


def _build_chat(
    role: Role, spec: ModelSpec, settings: Settings, usage: RunUsage | None, learner_waiting: bool
) -> BaseChatModel:
    # one usage handler per model so a fallback's calls count against its own budget
    callbacks = [usage.for_role(role, spec.name)] if usage else None
    if spec.vendor == "fake":
        return FakeChatModel(callbacks=callbacks)
    if spec.vendor != "gemini":
        raise AIUnavailable(NOT_CONFIGURED)
    max_wait = LEARNER_MAX_WAIT_MS if learner_waiting else None  # None lets background jobs wait
    return ChatGoogleGenerativeAI(
        model=spec.name,
        api_key=_api_key(settings.gemini_api_key),
        # Only Gemini 3 has thinking levels. Older models set thinking with a token budget.
        thinking_level=(
            getattr(settings, f"ai_{role}_thinking") if spec.name.startswith("gemini-3") else None
        ),
        temperature=None,  # the API's default, rather than LangChain's 0.7
        retries=1,  # one attempt: its default of 6 would spend quota on every retry
        timeout=TIMEOUT_SECONDS,
        callbacks=callbacks,
        rate_limiter=_rate_limiter(spec.name, settings, max_wait),  # waits for a turn first
    )


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
    vendor, model = _vendor_and_model(Role.EMBEDDER, settings)
    if vendor == "fake":
        embeddings = FakeEmbeddings()
    elif vendor == "gemini":
        embeddings = GoogleGenerativeAIEmbeddings(
            model=model,
            api_key=_api_key(settings.gemini_api_key),
            # a fixed size matching the pgvector column using Matryoshka-style truncation
            output_dimensionality=EMBEDDING_DIMENSIONS,
        )
    else:
        raise AIUnavailable(NOT_CONFIGURED)
    # Step 2: wrap it with the rate limiter and usage counting if either applies
    max_wait = LEARNER_MAX_WAIT_MS if learner_waiting else None
    limiter = _rate_limiter(model, settings, max_wait) if vendor == "gemini" else None
    name = model_name(Role.EMBEDDER, settings)
    role_usage = usage.for_role(Role.EMBEDDER, name) if usage else None
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
