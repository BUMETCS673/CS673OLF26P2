"""Shared LangGraph setup for compiling once, thread configs, and retries with fallbacks."""

from collections.abc import Callable, Mapping
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import RetryPolicy

from app.ai.models import AITransient

# LangGraph reruns only the failed node, with backoff.
TRANSIENT_RETRY = RetryPolicy(max_attempts=3, retry_on=AITransient)

# Maps a node to the state update that replaces it once its retries run out.
Fallbacks = Mapping[str, Callable[[dict[str, Any]], dict[str, Any]]]

_compiled: dict[tuple[int, int], CompiledStateGraph] = {}


def compiled(graph: StateGraph, checkpointer: BaseCheckpointSaver) -> CompiledStateGraph:
    """Compiles each graph once per checkpointer, since the process shares one checkpointer."""
    key = (id(graph), id(checkpointer))
    if key not in _compiled:
        _compiled[key] = graph.compile(checkpointer=checkpointer)
    return _compiled[key]


def thread_config(thread_id: str, run_name: str, **config: Any) -> RunnableConfig:
    return {"configurable": {"thread_id": thread_id}, "run_name": run_name, **config}


async def invoke_with_fallbacks(
    graph: CompiledStateGraph,
    graph_input: Any,
    config: RunnableConfig,
    fallbacks: Fallbacks,
    **kwargs: Any,
) -> dict[str, Any]:
    """Runs the graph, and continues from the saved state when a node with a fallback gives up."""
    while True:
        try:
            return await graph.ainvoke(graph_input, config, **kwargs)
        except AITransient:
            snapshot = await graph.aget_state(config)
            node = snapshot.next[0] if snapshot.next else None
            if node not in fallbacks:
                raise
            await graph.aupdate_state(config, fallbacks[node](snapshot.values), as_node=node)
            graph_input = None  # None resumes from the saved state
