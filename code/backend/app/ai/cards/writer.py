"""The model's turn to write cards, with or without one search first."""

from collections.abc import Awaitable, Callable

from langchain.agents import create_agent
from langchain.agents.middleware import (
    ModelRequest,
    ModelResponse,
    ToolCallLimitMiddleware,
    wrap_model_call,
)
from langchain.agents.structured_output import ToolStrategy
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from app.ai.cards.prompts import SEARCH_BODY
from app.ai.knowledge.retrieval import KnowledgeRetriever, labelled_text
from app.ai.knowledge.tools import KnowledgeContext, search_materials
from app.ai.models import (
    BAD_REPLY,
    AIUnavailable,
    ChatModel,
    agent_model,
    ai_errors,
    structured_reply,
)
from app.ai.schemas import CardBatch, CardDraft


@wrap_model_call
async def _search_only_once(
    request: ModelRequest, handler: Callable[[ModelRequest], Awaitable[ModelResponse]]
) -> ModelResponse:
    """After a search, only the tool that returns cards is left, so the next turn must write."""
    if any(isinstance(message, ToolMessage) for message in request.messages):
        request = request.override(tools=[])
    return await handler(request)


async def write_with_search(
    model: ChatModel, system: str, body: str, retriever: KnowledgeRetriever
) -> tuple[list[CardDraft], list[str], list[str]]:
    """The cards, what the search found, and those chunks' IDs. It costs at most two model calls."""
    first, fallbacks = agent_model(model)
    agent = create_agent(
        first,
        [search_materials],
        system_prompt=system,
        # Cards come back through a tool, since a model can't always use tools and a provider's
        # own JSON mode together. It also makes each turn end in a tool call, never in plain text.
        response_format=ToolStrategy(CardBatch, handle_errors=False),
        # The limit stops two searches asked for in one turn, which `_search_only_once` can't.
        middleware=[
            ToolCallLimitMiddleware(tool_name=search_materials.name, run_limit=1),
            _search_only_once,
            *fallbacks,
        ],
        context_schema=KnowledgeContext,
    )
    try:
        with ai_errors():
            result = await agent.ainvoke(
                {"messages": [HumanMessage(f"{body}\n\n{SEARCH_BODY}")]},
                context=KnowledgeContext(retriever=retriever),
            )
    except BAD_REPLY:
        raise AIUnavailable() from None

    batch = result.get("structured_response")
    documents = [
        document
        for message in result["messages"]
        if isinstance(message, ToolMessage) and message.artifact
        for document in message.artifact
    ]
    found = [labelled_text(document) for document in documents]
    chunk_ids = [document.id for document in documents if document.id]
    return (batch.cards if batch else []), found, chunk_ids


async def write_directly(model: ChatModel, system: str, body: str) -> list[CardDraft]:
    """One call with no tools, for a file's material or a repair."""
    batch = await structured_reply(model, CardBatch, [SystemMessage(system), HumanMessage(body)])
    return batch.cards if batch else []
