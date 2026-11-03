"""The graph that recommends fixes for problem cards, and waits for the learner to decide.

    START -> diagnose -> judge -> review (pauses) -> END

`diagnose` and `judge` each make one call covering every card, and `diagnose` skips `judge` if it
has nothing to check. An option is dropped if any of its new cards fails. If the judge can't
answer, the options stay and the review is marked "skipped", so the learner is warned.

The run pauses at `review` until the learner decides. The checkpointer saves it there, so the
decisions can arrive in a later request, on any process. The graph changes nothing in the deck:
whoever resumes it applies the decisions.

A failed `diagnose` raises AIRateLimited or AIUnavailable, and the job retries the run.
"""

import logging
from dataclasses import dataclass

from langchain_core.exceptions import OutputParserException
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import Command, interrupt
from pydantic import ValidationError

from app.ai.judge import PASSED, SKIPPED, NoEvidence, judge_cards
from app.ai.models import AIUnavailable, ai_errors
from app.ai.problem_cards.checks import keep_approved, recommendations_from
from app.ai.problem_cards.context import ProblemCardContext
from app.ai.problem_cards.prompts import FIX_RULES, fix_body
from app.ai.problem_cards.state import ProblemCardState
from app.ai.schemas import CardDraft, Diagnosis

logger = logging.getLogger(__name__)


async def _diagnose(_: ProblemCardState, runtime: Runtime[ProblemCardContext]) -> dict:
    context = runtime.context
    structured = context.writer.with_structured_output(Diagnosis)
    messages = [SystemMessage(FIX_RULES), HumanMessage(fix_body(context.cards))]
    try:
        with ai_errors():
            diagnosis = await structured.ainvoke(messages)
    except (OutputParserException, ValidationError):
        raise AIUnavailable() from None
    if diagnosis is None:
        return {"recommendations": [], "shared_cause": None}

    recommendations = recommendations_from(diagnosis, context.cards, context.existing_fronts)
    cause = (diagnosis.shared_cause or "").strip()
    return {
        "recommendations": recommendations,
        "shared_cause": cause if cause and len(recommendations) >= 2 else None,
    }


async def _judge(state: ProblemCardState, runtime: Runtime[ProblemCardContext]) -> dict:
    # There's no source to check against, so the judge uses its own knowledge. The deck's cards
    # aren't sent, because a rewrite means to ask what the original asks, and would look like a
    # repeat.
    candidates = [
        CardDraft(**card)
        for recommendation in state["recommendations"]
        for option in recommendation["options"]
        for card in option["cards"]
    ]
    verdicts = await judge_cards(runtime.context.judge, candidates, NoEvidence())
    if not verdicts:
        return {"verification": SKIPPED}

    kept = keep_approved(state["recommendations"], verdicts)
    return {
        "recommendations": kept,
        # A shared cause needs at least two cards, and the check may have removed some.
        "shared_cause": state["shared_cause"] if len(kept) >= 2 else None,
    }


def _review(state: ProblemCardState) -> dict:
    if not state["recommendations"]:
        return {"decisions": []}
    # This saves the run and stops. On resume the node starts again from its first line, and
    # interrupt() returns the learner's answer, so nothing above it may have side effects.
    return {"decisions": interrupt(state["recommendations"])}


def _after_diagnose(state: ProblemCardState) -> str:
    return "judge" if state["recommendations"] else "review"


def _build_graph() -> StateGraph:
    graph = StateGraph(ProblemCardState, context_schema=ProblemCardContext)
    graph.add_node("diagnose", _diagnose)
    graph.add_node("judge", _judge)
    graph.add_node("review", _review)
    graph.add_edge(START, "diagnose")
    graph.add_conditional_edges("diagnose", _after_diagnose, ["judge", "review"])
    graph.add_edge("judge", "review")
    graph.add_edge("review", END)
    return graph


_GRAPH = _build_graph()  # compiled per run, with that run's checkpointer


@dataclass(frozen=True)
class ReviewOutcome:
    recommendations: list[dict]
    shared_cause: str | None
    verification: str


def _thread(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}, "run_name": "problem_card_review"}


async def start_review(
    context: ProblemCardContext, checkpointer: BaseCheckpointSaver, thread_id: str
) -> ReviewOutcome:
    """Run until the pause, or to the end if no card has a recommendation."""
    state = await _GRAPH.compile(checkpointer=checkpointer).ainvoke(
        {
            "recommendations": [],
            "shared_cause": None,
            "verification": PASSED,
            "decisions": [],
        },
        _thread(thread_id),
        context=context,
    )
    # Counts only, since a reason can quote learner content.
    logger.info(
        "problem_cards cards=%d recommended=%d verification=%s",
        len(context.cards),
        len(state["recommendations"]),
        state["verification"],
    )
    return ReviewOutcome(state["recommendations"], state["shared_cause"], state["verification"])


async def resume_review(
    checkpointer: BaseCheckpointSaver, thread_id: str, decisions: list[dict]
) -> list[dict]:
    """Continue a paused run. It needs no context, since only `review` runs and reads none."""
    state = await _GRAPH.compile(checkpointer=checkpointer).ainvoke(
        Command(resume=decisions), _thread(thread_id)
    )
    return state["decisions"]
