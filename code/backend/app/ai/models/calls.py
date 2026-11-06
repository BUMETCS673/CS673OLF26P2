"""Calling a model chain for a structured reply, or handing it to an agent."""

import logging
from collections.abc import Awaitable, Callable, Sequence

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain.agents.structured_output import StructuredOutputError
from langchain_core.exceptions import OutputParserException
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.runnables import Runnable, RunnableWithFallbacks
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, ValidationError

from app.ai.failures import FALL_BACK_ON
from app.ai.models.errors import AIRateLimited, AITransient, AIUnavailable, ai_errors
from app.ai.models.factory import ChatModel

logger = logging.getLogger(__name__)

# Replies that don't fit the requested shape.
BAD_REPLY = (OutputParserException, ValidationError, StructuredOutputError)


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
