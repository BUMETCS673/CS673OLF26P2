"""The graph that writes, checks and repairs a batch of cards.

    START -> writer -> validate -> judge -> END
                          ^          |
                          |          v
                          +------ repair

`writer` may search once before writing, inside its own agent. `repair` runs at most once, which
is what guarantees the cycle ends. LangGraph retries each model node on transient failures.

- `writer` failing fails the run.
- `judge` keeps its cards and marks the batch "skipped" if it gets no usable answer.
- `repair` keeps the approved cards if its call fails.

Cards that still fail after the repair are dropped.
"""

import logging
import uuid
from dataclasses import dataclass, field

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from app.ai.cards import prompts
from app.ai.cards.checks import back_fits, clean_cards, normalized_fronts
from app.ai.cards.context import CardContext
from app.ai.cards.state import CardState
from app.ai.cards.writer import write_directly, write_with_search
from app.ai.graphs import TRANSIENT_RETRY, invoke_with_fallbacks, thread_config
from app.ai.judge import PASSED, SKIPPED, judge_cards
from app.ai.models import AIRateLimited, AITransient, AIUnavailable
from app.ai.schemas import CardDraft

logger = logging.getLogger(__name__)

MAX_REPAIRS = 1  # bounds the cycle to at most one extra write per run


async def _writer(_: CardState, runtime: Runtime[CardContext]) -> dict:
    context = runtime.context  # models, request and tools fixed for the run
    system = prompts.rules(context.count)
    if context.retriever is None:  # file mode or nothing to search so one structured call
        return {"pending": await write_directly(context.writer, system, context.body)}
    # prompt mode uses an agent that may search once before answering
    cards, found, chunk_ids = await write_with_search(
        context.writer, system, context.body, context.retriever
    )
    return {"pending": cards, "found": found, "source_chunk_ids": chunk_ids}  # partial update


def _validate(state: CardState, runtime: Runtime[CardContext]) -> dict:
    """The rules a program can check come first, since failing them costs no judge call."""
    context = runtime.context
    approved = state["approved"]
    # Step 1: drop empty cards, repeats of the deck or of approved ones and extras past count
    cards = clean_cards(
        state["pending"],
        context.count - len(approved),  # only as many as are still missing
        context.taken_fronts,  # the deck's fronts normalized once per run
        normalized_fronts(card.front for card in approved),
    )
    # Step 2: send cards with a too-long back to repair rather than the judge
    too_long = f"The back is longer than {prompts.BACK_MAX_WORDS} words."
    return {
        "pending": [card for card in cards if back_fits(card)],
        "failed": [(card, too_long) for card in cards if not back_fits(card)],  # with a reason
    }


def _unchecked(state: CardState) -> dict:
    """Keeps the pending cards and marks the batch unchecked."""
    # the judge's fallback keeps the cards flagged as unchecked instead of losing them
    return {"pending": [], "approved": state["pending"], "failed": [], "verification": SKIPPED}


async def _judge(state: CardState, runtime: Runtime[CardContext]) -> dict:
    context = runtime.context
    pending = state["pending"]
    # Step 1: gather the mode's evidence and the deck's similar cards to judge against
    evidence = context.evidence.with_found(state["found"])  # prompt mode adds the search results
    existing = await context.find_existing(pending)  # near-duplicates already in the deck
    # Step 2: judge the batch in one call raise_transient lets RetryPolicy retry this node
    verdicts = await judge_cards(context.judge, pending, evidence, existing, raise_transient=True)
    if not verdicts:  # no usable answer
        return _unchecked(state)

    # Step 3: sort each card into approved or failed with the judge's reason
    approved, failed = [], list(state["failed"])  # keep validate's failures for the repair too
    for index, card in enumerate(pending):
        verdict = verdicts.get(index)
        if verdict is None:  # a card the judge skipped is not approved
            failed.append((card, "The checker gave no verdict on this card."))
        elif verdict.ok:
            approved.append(card)
        else:
            failed.append((card, verdict.reason or "It failed the check."))
    # approved has an add reducer so these append to earlier rounds
    return {"pending": [], "approved": approved, "failed": failed}


async def _repair(state: CardState, runtime: Runtime[CardContext]) -> dict:
    context = runtime.context
    failed = state["failed"]
    # Step 1: one prompt with the failed cards and their reasons and the approved ones to avoid
    body = prompts.repair_body(
        prompts.with_found(context.body, state["found"]), failed, state["approved"]
    )
    # Step 2: ask the writer for replacements in one structured call without search
    try:
        cards = await write_directly(context.writer, prompts.rules(len(failed)), body)
    except AITransient:
        raise  # retried by LangGraph, then replaced by _no_repair
    except (AIRateLimited, AIUnavailable) as error:
        logger.warning("card_repair outcome=failed type=%s", type(error).__name__)
        return _no_repair(state)  # keep what's approved rather than fail the run
    # the new cards go back through validate and judge and repairs counts toward MAX_REPAIRS
    return {"pending": cards, "failed": [], "repairs": 1}


def _no_repair(_: CardState) -> dict:
    """Ends the repair with no new cards, which keeps the approved ones."""
    return {"pending": [], "failed": [], "repairs": 1}  # repairs=1 stops the loop from coming back


def _can_repair(state: CardState) -> bool:
    return bool(state["failed"]) and state["repairs"] < MAX_REPAIRS


def _after_validate(state: CardState) -> str:
    if state["pending"]:  # cards left to judge
        return "judge"
    # skip the judge call when nothing is left to check
    return "repair" if _can_repair(state) else END


def _after_judge(state: CardState) -> str:
    return "repair" if _can_repair(state) else END


def _build_graph():
    graph = StateGraph(CardState, context_schema=CardContext)  # context stays read-only for the run
    # model nodes retry on transient errors and validate is pure code with no policy
    graph.add_node("writer", _writer, retry_policy=TRANSIENT_RETRY)
    graph.add_node("validate", _validate)
    graph.add_node("judge", _judge, retry_policy=TRANSIENT_RETRY)
    graph.add_node("repair", _repair, retry_policy=TRANSIENT_RETRY)
    graph.add_edge(START, "writer")
    graph.add_edge("writer", "validate")
    graph.add_conditional_edges("validate", _after_validate, ["judge", "repair", END])
    graph.add_conditional_edges("judge", _after_judge, ["repair", END])
    graph.add_edge("repair", "validate")  # the cycle bounded by MAX_REPAIRS
    # The saver holds each run's state for the fallbacks, and CardDraft is listed to deserialize.
    # in memory since a card run lives within one job
    saver = InMemorySaver(serde=JsonPlusSerializer(allowed_msgpack_modules=[CardDraft]))
    return graph.compile(checkpointer=saver)


_GRAPH = _build_graph()  # compiled once at import shared by every run in the process
_FALLBACKS = {"judge": _unchecked, "repair": _no_repair}  # used when retries run out


def _start() -> dict:
    return {
        "pending": [],
        "approved": [],
        "failed": [],
        "repairs": 0,
        "verification": PASSED,
        "found": [],
        "source_chunk_ids": [],
    }


@dataclass(frozen=True)
class CardOutcome:
    cards: list[CardDraft]
    verification: str
    repairs: int
    source_chunk_ids: list[str] = field(default_factory=list)


async def run_card_graph(context: CardContext) -> CardOutcome:
    """Run to the end. Raises AIRateLimited or AIUnavailable if the writer fails."""
    thread_id = str(uuid.uuid4())  # a fresh thread per run so runs never share state
    # Metadata passes down to every model call in the run, so traces show the prompt version.
    config = thread_config(
        thread_id, "card_generation", metadata={"prompt_version": prompts.PROMPT_VERSION}
    )
    try:
        state = await invoke_with_fallbacks(_GRAPH, _start(), config, _FALLBACKS, context=context)
    finally:
        await _GRAPH.checkpointer.adelete_thread(thread_id)  # free the memory success or not
    # Counts only, since card text and a judge's reasons can hold learner content.
    logger.info(
        "card_graph kept=%d repairs=%d verification=%s",
        len(state["approved"]),
        state["repairs"],
        state["verification"],
    )
    return CardOutcome(
        state["approved"], state["verification"], state["repairs"], state["source_chunk_ids"]
    )
