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
    # a ToolMessage means the search already ran so only the answer tool is left
    if any(isinstance(message, ToolMessage) for message in request.messages):
        # override returns a copy and leaves the original intact
        request = request.override(tools=[])
    return await handler(request)


async def write_with_search(
    model: ChatModel, system: str, body: str, retriever: KnowledgeRetriever
) -> tuple[list[CardDraft], list[str], list[str]]:
    """The cards, what the search found, and those chunks' IDs. It costs at most two model calls."""
    # Step 1: build an agent with one search tool that returns its cards through a tool call
    first, fallbacks = agent_model(model)  # the chain moves into middleware
    agent = create_agent(  # LangChain's prebuilt ReAct loop on LangGraph
        first,
        [search_materials],
        system_prompt=system,
        # Cards come back through a tool, since a model can't always use tools and a provider's
        # own JSON mode together. It also makes each turn end in a tool call, never in plain text.
        response_format=ToolStrategy(CardBatch, handle_errors=False),  # raise on a bad reply
        # The limit stops two searches asked for in one turn, which `_search_only_once` can't.
        middleware=[
            ToolCallLimitMiddleware(tool_name=search_materials.name, run_limit=1),
            _search_only_once,
            *fallbacks,  # innermost so a fallback model sees the same narrowed request
        ],
        context_schema=KnowledgeContext,  # the retriever injected so the model can't pick it
    )
    # Step 2: run it searching at most once before writing
    try:
        with ai_errors():
            result = await agent.ainvoke(
                {"messages": [HumanMessage(f"{body}\n\n{SEARCH_BODY}")]},
                context=KnowledgeContext(retriever=retriever),
            )
    except BAD_REPLY:  # cards that don't fit the schema
        raise AIUnavailable() from None

    # Step 3: pull out the cards and the passages the search returned
    batch = result.get("structured_response")  # None if the agent never answered
    documents = [
        document
        for message in result["messages"]
        # the tool's artifact holds the Documents while the model only saw their text
        if isinstance(message, ToolMessage) and message.artifact
        for document in message.artifact
    ]
    found = [labelled_text(document) for document in documents]  # with each passage's origin
    chunk_ids = [document.id for document in documents if document.id]  # for reports later
    return (batch.cards if batch else []), found, chunk_ids


async def write_directly(model: ChatModel, system: str, body: str) -> list[CardDraft]:
    """One call with no tools, for a file's material or a repair."""
    batch = await structured_reply(model, CardBatch, [SystemMessage(system), HumanMessage(body)])
    return batch.cards if batch else []  # no usable reply gives no cards
