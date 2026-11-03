"""The deck tutor: one chat turn, which can pause while the learner decides on proposed cards.

    START -> agent -> END                            (a reply)
             agent -> check -> review (pauses) -> END    (proposed cards)

`agent` runs a tool-calling loop of at most MAX_AGENT_CALLS model calls. The checkpointer is the
chat's memory: each turn adds to `messages` under the same thread, and the model only sees the
latest HISTORY_WINDOW of them. The graph changes nothing in the deck: whoever resumes it adds the
accepted cards.
"""

import logging
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from langchain.agents import create_agent
from langchain.agents.middleware import ModelRequest, ModelResponse, wrap_model_call
from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    ToolMessage,
    trim_messages,
)
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import Command, interrupt

from app.ai.cards.checks import back_fits, clean_cards
from app.ai.judge import PASSED, SKIPPED, NoEvidence, judge_cards
from app.ai.models import AIRateLimited, AIUnavailable, Role, ai_errors
from app.ai.prompting import EXISTING_CARDS
from app.ai.schemas import CardDraft
from app.ai.tutor.context import TutorContext
from app.ai.tutor.prompts import MAX_PROPOSED_CARDS, tutor_system
from app.ai.tutor.state import TutorState
from app.ai.tutor.tools import TUTOR_TOOLS, propose_cards

logger = logging.getLogger(__name__)

MAX_AGENT_CALLS = 3
HISTORY_WINDOW = 12  # messages sent to the model
MAX_REPLY_CHARS = 4000  # shown to the learner
MAX_MESSAGES = 100  # shown messages before the learner must reset
# A turn's worst case, which the budgets reserve before it starts.
TURN_COST = {Role.WRITER: MAX_AGENT_CALLS, Role.JUDGE: 1, Role.EMBEDDER: MAX_AGENT_CALLS - 1}
TURN_MAX_CALLS = sum(TURN_COST.values())

CANT_ANSWER = "I couldn't work that out. Could you ask it another way?"
CANT_VERIFY = "I couldn't write a card that passed the accuracy checks, so I didn't suggest one."


def _is_notice(message: AnyMessage) -> bool:
    return bool(message.additional_kwargs.get("error"))


def _notice(text: str) -> AIMessage:
    """A failure notice for the learner, which the model never sees."""
    return AIMessage(text, additional_kwargs={"error": True})


def _calls_this_turn(messages: Sequence[AnyMessage]) -> int:
    calls = 0
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            break
        calls += isinstance(message, AIMessage)
    return calls


@wrap_model_call
async def _answer_on_last_call(
    request: ModelRequest, handler: Callable[[ModelRequest], Awaitable[ModelResponse]]
) -> ModelResponse:
    """The last call gets no tools, so the loop ends in a reply rather than being cut off."""
    if _calls_this_turn(request.messages) + 1 >= MAX_AGENT_CALLS:
        request = request.override(tools=[])
    return await handler(request)


async def _run_agent(context: TutorContext, history: list[AnyMessage]) -> list[AnyMessage]:
    """The turn's new messages. Starting on a human message keeps tool calls with their results."""
    window = trim_messages(
        history, strategy="last", token_counter=len, max_tokens=HISTORY_WINDOW, start_on="human"
    )
    agent = create_agent(
        context.writer,
        TUTOR_TOOLS,
        system_prompt=tutor_system(context.deck_name),
        middleware=[_answer_on_last_call],
        context_schema=TutorContext,
        checkpointer=False,  # otherwise it saves its own steps in the tutor's checkpointer
    )
    with ai_errors():
        result = await agent.ainvoke({"messages": window}, context=context)
    return result["messages"][len(window):]


def _proposed_cards(messages: Sequence[AnyMessage]) -> list[dict]:
    """The last accepted propose_cards call, since a call with bad arguments has no artifact."""
    for message in reversed(messages):
        if (
            isinstance(message, ToolMessage)
            and message.name == propose_cards.name
            and message.artifact
        ):
            return message.artifact
    return []


async def _agent(state: TutorState, runtime: Runtime[TutorContext]) -> dict:
    history = [message for message in state["messages"] if not _is_notice(message)]
    try:
        new = await _run_agent(runtime.context, history)
    except (AIRateLimited, AIUnavailable) as error:
        logger.warning("tutor outcome=agent_failed type=%s", type(error).__name__)
        return {"messages": [_notice(error.message)]}

    raw_cards = _proposed_cards(new)
    if not raw_cards and not (isinstance(new[-1], AIMessage) and new[-1].text.strip()):
        new.append(AIMessage(CANT_ANSWER))
    return {"messages": new, "raw_cards": raw_cards}


async def _check(state: TutorState, runtime: Runtime[TutorContext]) -> dict:
    context = runtime.context
    drafts = clean_cards(
        [CardDraft(**card) for card in state["raw_cards"]],
        MAX_PROPOSED_CARDS,
        context.taken_fronts,
    )
    drafts = [draft for draft in drafts if back_fits(draft)]
    if not drafts:
        return {"messages": [AIMessage(CANT_VERIFY)]}

    # The newest first, as card generation sends them. `cards` is oldest first.
    existing = [
        CardDraft(front=card["front"], back=card["back"])
        for card in reversed(context.cards[-EXISTING_CARDS:])
    ]
    verdicts = await judge_cards(context.judge, drafts, NoEvidence(), existing)
    # No usable answer keeps the cards with a warning. Otherwise only explicit approvals stay.
    kept = drafts if not verdicts else [
        draft
        for index, draft in enumerate(drafts)
        if index in verdicts and verdicts[index].ok
    ]
    if not kept:
        return {"messages": [AIMessage(CANT_VERIFY)]}
    return {
        "proposal": {"id": str(uuid.uuid4()), "cards": [draft.model_dump() for draft in kept]},
        "verification": PASSED if verdicts else SKIPPED,
    }


def _review(state: TutorState) -> dict:
    # This saves the run and stops. On resume the node starts again from its first line, and
    # interrupt() returns the closing message, so nothing above it may have side effects.
    closing = interrupt(state["proposal"])
    return {"messages": [AIMessage(closing)], "proposal": None}


def _after_agent(state: TutorState) -> str:
    return "check" if state.get("raw_cards") else END


def _after_check(state: TutorState) -> str:
    return "review" if state.get("proposal") else END


def _build_graph() -> StateGraph:
    graph = StateGraph(TutorState, context_schema=TutorContext)
    graph.add_node("agent", _agent)
    graph.add_node("check", _check)
    graph.add_node("review", _review)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", _after_agent, ["check", END])
    graph.add_conditional_edges("check", _after_check, ["review", END])
    graph.add_edge("review", END)
    return graph


_GRAPH = _build_graph()  # compiled per run, with that run's checkpointer


@dataclass(frozen=True)
class TurnOutcome:
    messages: list[dict]
    proposal: dict | None
    verification: str


def _thread(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}, "run_name": "deck_tutor"}


def _for_learner(messages: Sequence[AnyMessage]) -> list[dict]:
    """The chat as the learner sees it, without tool calls and their results."""
    shown = []
    for message in messages:
        if isinstance(message, HumanMessage):
            shown.append({"role": "user", "text": message.text})
        elif isinstance(message, AIMessage) and message.text.strip():
            shown.append({
                "role": "tutor",
                "text": message.text[:MAX_REPLY_CHARS],
                **({"error": True} if _is_notice(message) else {}),
            })
    return shown


async def run_turn(
    context: TutorContext, checkpointer: BaseCheckpointSaver, thread_id: str, text: str
) -> TurnOutcome:
    """Add the learner's message and run until a reply or a proposal."""
    # `messages` has a reducer, so this appends. The other fields start fresh each turn.
    state = await _GRAPH.compile(checkpointer=checkpointer).ainvoke(
        {
            "messages": [HumanMessage(text)],
            "raw_cards": [],
            "proposal": None,
            "verification": PASSED,
        },
        _thread(thread_id),
        context=context,
        # Saving once per turn avoids rewriting the chat at every step. A crash loses that turn.
        durability="exit",
    )
    # Counts only, since messages hold learner content.
    logger.info("tutor messages=%d proposal=%s", len(state["messages"]), bool(state["proposal"]))
    return TurnOutcome(_for_learner(state["messages"]), state["proposal"], state["verification"])


async def resume_turn(checkpointer: BaseCheckpointSaver, thread_id: str, closing: str) -> None:
    """Finish a paused turn. It needs no context, since only `review` runs and reads none."""
    await _GRAPH.compile(checkpointer=checkpointer).ainvoke(
        Command(resume=closing), _thread(thread_id)
    )


async def read_messages(checkpointer: BaseCheckpointSaver, thread_id: str) -> list[dict]:
    snapshot = await _GRAPH.compile(checkpointer=checkpointer).aget_state(_thread(thread_id))
    return _for_learner(snapshot.values.get("messages", []))
