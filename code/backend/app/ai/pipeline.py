"""Self-correcting card generation, implemented as a LangGraph state graph.

Graph topology::

    START -> generate -> validate -> judge -> END
                            ^          |
                            |          v
                            +------ repair (at most MAX_REPAIRS times)

``validate`` also routes directly to ``repair`` or END when no cards are pending.

Failure handling by node:

* ``generate`` retries AITransient once. Any other failure propagates as AIRateLimited or
  AIUnavailable, and the route maps it to an HTTP error.
* ``judge`` keeps the pending cards and sets ``verification`` to SKIPPED if it gets no usable
  answer. The learner is warned that the batch was not checked.
* ``repair`` keeps the cards already approved if its call fails.

Cards that still fail after the last repair are dropped.

This module does not depend on Flask or SQLAlchemy. Providers are passed in by the caller.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from operator import add
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy

from app.ai.cleanup import clean_drafts
from app.ai.prompts import build_judge_prompt, build_repair_prompt
from app.ai.provider import (
    AIRateLimited,
    AITransient,
    AIUnavailable,
    Attachment,
    CardDraft,
    Prompt,
    Provider,
)

logger = logging.getLogger(__name__)

# Upper bound on repair rounds. This is what guarantees the graph's cycle terminates.
MAX_REPAIRS = 1
GENERATE_MAX_ATTEMPTS = 2
# Worst case per request: generate attempts, the first judge call, then one write and one judge
# call per repair. The route reserves this many calls against the site cap before starting.
MAX_MODEL_CALLS = GENERATE_MAX_ATTEMPTS + 1 + 2 * MAX_REPAIRS
BACK_MAX_WORDS = 5  # must match rule 3 in prompts.RULES
# Values of PipelineState["verification"].
PASSED = "passed"    # every kept card went through the judge
SKIPPED = "skipped"  # the judge gave no usable answer, so some kept cards were not checked


@dataclass(frozen=True)
class PipelineRequest:
    """Immutable inputs for one run. Kept out of the graph state because nodes never change them."""

    prompt: Prompt                         # sent by the generate node
    count: int                             # maximum cards to keep from the first write
    existing_fronts: Sequence[str]         # all fronts in the deck, used for deduplication
    existing: Sequence[CardDraft] = ()     # newest cards in the deck, sent to the judge
    topic: str | None = None               # prompt mode: what was requested, not evidence
    file_text: str | None = None           # file mode, TXT or MD: evidence for the judge
    attachment: Attachment | None = None   # file mode, PDF: evidence for the judge


@dataclass(frozen=True)
class PipelineResult:
    """What the route needs from the final state."""

    drafts: list[CardDraft]
    model_calls: int
    verification: str


class PipelineState(TypedDict):
    """State shared by all nodes.

    Each node returns a partial update, which LangGraph merges field by field. A plain field is
    overwritten by the new value. A field annotated with a reducer, such as ``add``, is combined
    with the current value as ``add(current, update)``.

    A card moves through the fields as follows: ``pending`` after it is written, then either
    ``approved`` or ``failed`` after it is checked. ``repair`` replaces ``failed`` cards with new
    ``pending`` ones.
    """

    pending: list[CardDraft]                   # overwritten: cards awaiting the next check
    approved: Annotated[list[CardDraft], add]  # reducer: concatenated across rounds
    failed: list[tuple[CardDraft, str]]        # overwritten: (card, reason) for this round
    repairs: Annotated[int, add]               # reducer: return 1 to increment
    model_calls: Annotated[int, add]           # reducer: return the number of calls just made
    verification: str                          # overwritten: PASSED or SKIPPED


def _verdicts_by_index(verdicts: list) -> dict[int, dict]:
    """Map each candidate index to its first well-formed verdict, ignoring malformed entries."""
    by_index: dict[int, dict] = {}
    for verdict in verdicts:
        # Model output is untrusted. bool is a subclass of int, so isinstance() would wrongly
        # accept true and false as indexes.
        if isinstance(verdict, dict) and type(verdict.get("index")) is int:
            # setdefault() keeps the first verdict if the model repeats an index.
            by_index.setdefault(verdict["index"], verdict)
    return by_index


def build_graph(writer: Provider, judge: Provider, request: PipelineRequest):
    """Build and compile the graph for one request.

    Nodes capture ``writer``, ``judge`` and ``request`` by closure, so the state holds only the
    values that change during a run. ``writer`` and ``judge`` may use different models.
    """

    # Nodes receive the current state and return only the fields to update. They must not mutate
    # ``state`` in place, because LangGraph applies changes through the returned update.

    # A failed attempt returns no state update, so attempts are counted here instead of in the
    # state. The counter lives for one request because the graph is built per request.
    generate_attempts = 0

    def generate_node(state: PipelineState) -> dict:
        nonlocal generate_attempts
        generate_attempts += 1

        # Provider errors are not caught here. The node's RetryPolicy re-runs this function on
        # AITransient. Any other error, or the last failed attempt, aborts the run and propagates
        # out of invoke(). A reply with no usable cards is not an error and ends the run normally.
        raw = writer.generate_cards(request.prompt)

        # clean_drafts() drops malformed cards and exact duplicates of cards in the deck.
        return {
            "pending": clean_drafts(raw, request.count, request.existing_fronts),
            "model_calls": generate_attempts,
        }

    def validate_node(state: PipelineState) -> dict:
        # Check local rules first, so that cards failing them cost no judge call.
        pending, failed = [], []
        for card in state["pending"]:
            if len(card.back.split()) > BACK_MAX_WORDS:
                failed.append((card, f"The back is longer than {BACK_MAX_WORDS} words."))
            else:
                pending.append(card)

        # ``failed`` has no reducer, so this replaces the previous round's failures.
        return {"pending": pending, "failed": failed}

    def judge_node(state: PipelineState) -> dict:
        # One call checks the whole batch. The source is sent again as evidence for the check.
        pending = state["pending"]
        prompt = build_judge_prompt(
            pending,
            topic=request.topic,
            file_text=request.file_text,
            attachment=request.attachment,
            existing=request.existing,
        )

        # A failed call and an unusable reply are handled the same way below. AITransient is a
        # subclass of AIUnavailable, so it lands here too and is not retried.
        try:
            verdicts = _verdicts_by_index(judge.judge_cards(prompt))
        except (AIRateLimited, AIUnavailable):
            verdicts = {}

        # No usable answer says nothing about the cards, so keep them and mark the batch as
        # unverified. Clearing ``failed`` makes after_judge() route to END.
        if not verdicts:
            return {
                "pending": [], "approved": pending, "failed": [],
                "model_calls": 1, "verification": SKIPPED,
            }

        # Start from the existing failures so that cards rejected by validate_node are retained.
        approved, failed = [], list(state["failed"])

        # Only an explicit ok of true approves a card. A missing verdict counts as a failure.
        for index, card in enumerate(pending):
            verdict = verdicts.get(index)
            if verdict is None:
                failed.append((card, "The checker gave no verdict on this card."))
            elif verdict.get("ok") is True:
                approved.append(card)
            else:
                # The reason is passed to repair_node, which sends it back to the writer.
                reason = verdict.get("reason")
                failed.append((card, reason if isinstance(reason, str) else "It failed the check."))

        # ``approved`` has a reducer, so return only this round's cards, not the running total.
        return {"pending": [], "approved": approved, "failed": failed, "model_calls": 1}

    def repair_node(state: PipelineState) -> dict:
        # The writer sees why each card failed and which cards are already kept.
        kept = state["approved"]
        prompt = build_repair_prompt(request.prompt, state["failed"], kept)

        try:
            raw = writer.generate_cards(prompt)
        except (AIRateLimited, AIUnavailable):
            # Keep the approved cards. Empty lists make after_validate() route to END.
            return {"pending": [], "failed": [], "repairs": 1, "model_calls": 1}

        # Include approved fronts so that a replacement cannot duplicate a kept card.
        seen = [*request.existing_fronts, *(card.front for card in kept)]

        # Replacements become ``pending``, so the repair -> validate edge checks them like any
        # other card. Incrementing ``repairs`` is what bounds the cycle.
        return {
            "pending": clean_drafts(raw, len(state["failed"]), seen),
            "failed": [],
            "repairs": 1,
            "model_calls": 1,
        }

    # Routing functions read the state after the node's update is merged and return the name of
    # the next node. They must not modify state.

    def can_repair(state: PipelineState) -> bool:
        return bool(state["failed"]) and state["repairs"] < MAX_REPAIRS

    def after_validate(state: PipelineState) -> str:
        # Skip the judge when nothing is pending, which avoids a call with an empty batch.
        if state["pending"]:
            return "judge"
        return "repair" if can_repair(state) else END

    def after_judge(state: PipelineState) -> str:
        return "repair" if can_repair(state) else END

    # StateGraph is a builder. The schema defines the state fields and their reducers.
    graph = StateGraph(PipelineState)

    # Register each function under the name used by edges and routing functions. The retry policy
    # applies to generate only: judge_node and repair_node catch provider errors themselves, so a
    # policy on them would never fire.
    graph.add_node(
        "generate",
        generate_node,
        retry_policy=RetryPolicy(max_attempts=GENERATE_MAX_ATTEMPTS, retry_on=AITransient),
    )
    graph.add_node("validate", validate_node)
    graph.add_node("judge", judge_node)
    graph.add_node("repair", repair_node)

    # add_edge() defines a fixed transition. START marks the entry point.
    graph.add_edge(START, "generate")
    graph.add_edge("generate", "validate")

    # add_conditional_edges() calls the routing function after the source node finishes. The list
    # declares every destination the function can return. END terminates the run.
    graph.add_conditional_edges("validate", after_validate, ["judge", "repair", END])
    graph.add_conditional_edges("judge", after_judge, ["repair", END])

    # Closes the cycle. Replacements go through the same checks as the original cards.
    graph.add_edge("repair", "validate")

    # compile() validates the graph structure and returns a runnable object.
    return graph.compile()


def run_pipeline(writer: Provider, judge: Provider, request: PipelineRequest) -> PipelineResult:
    """Run the graph to completion. Raises AIRateLimited or AIUnavailable if generate fails."""
    # invoke() takes the initial state, runs until END and returns the final state. No checkpointer
    # is configured, so state is not persisted and an interrupted run cannot be resumed.
    # verification starts as PASSED, and judge_node overwrites it only when a check is skipped.
    state = build_graph(writer, judge, request).invoke(
        {
            "pending": [],
            "approved": [],
            "failed": [],
            "repairs": 0,
            "model_calls": 0,
            "verification": PASSED,
        }
    )

    # Log counts only. Card text and judge reasons can contain learner content.
    logger.info(
        "ai_pipeline kept=%d model_calls=%d repairs=%d verification=%s",
        len(state["approved"]), state["model_calls"], state["repairs"], state["verification"],
    )

    # Only ``approved`` is returned. Anything left in ``failed`` is dropped here.
    return PipelineResult(state["approved"], state["model_calls"], state["verification"])
