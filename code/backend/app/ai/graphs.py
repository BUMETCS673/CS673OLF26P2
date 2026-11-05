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
TRANSIENT_RETRY = RetryPolicy(max_attempts=3, retry_on=AITransient)  # never on permanent errors

# Maps a node to the state update that replaces it once its retries run out.
Fallbacks = Mapping[str, Callable[[dict[str, Any]], dict[str, Any]]]

_compiled: dict[tuple[int, int], CompiledStateGraph] = {}  # a process-wide cache


def compiled(graph: StateGraph, checkpointer: BaseCheckpointSaver) -> CompiledStateGraph:
    """Compiles each graph once per checkpointer, since the process shares one checkpointer."""
    key = (id(graph), id(checkpointer))  # identity works since both live for the whole process
    if key not in _compiled:
        _compiled[key] = graph.compile(checkpointer=checkpointer)  # validates and builds once
    return _compiled[key]


def thread_config(thread_id: str, run_name: str, **config: Any) -> RunnableConfig:
    # thread_id keys the run's saved state and run_name names its trace
    return {"configurable": {"thread_id": thread_id}, "run_name": run_name, **config}


async def invoke_with_fallbacks(
    graph: CompiledStateGraph,
    graph_input: Any,
    config: RunnableConfig,
    fallbacks: Fallbacks,
    **kwargs: Any,
) -> dict[str, Any]:
    """Runs the graph, and continues from the saved state when a node with a fallback gives up."""
    while True:  # one loop per node that gives up
        try:
            return await graph.ainvoke(graph_input, config, **kwargs)
        except AITransient:  # a node failed even after its RetryPolicy attempts
            # Step 1: find the node that failed from the last checkpoint
            snapshot = await graph.aget_state(config)
            node = snapshot.next[0] if snapshot.next else None  # the node that was about to run
            if node not in fallbacks:  # no fallback for it so the run fails
                raise
            # Step 2: write the fallback's update as if that node had run then resume
            await graph.aupdate_state(config, fallbacks[node](snapshot.values), as_node=node)
            graph_input = None  # None resumes from the saved state
