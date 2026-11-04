"""What the graph's nodes share as a run moves along."""

from operator import add
from typing import Annotated, TypedDict

from app.ai.schemas import CardDraft


class CardState(TypedDict):
    """Nodes return only what they change, and LangGraph merges it in.

    A card starts in `pending`, then moves to `approved` or `failed` once checked. `repair` turns
    `failed` cards into new `pending` ones. Fields with `add` build up, and the rest are replaced.
    """

    pending: list[CardDraft]
    approved: Annotated[list[CardDraft], add]
    failed: list[tuple[CardDraft, str]]  # each card and why it failed, for this round only
    repairs: Annotated[int, add]
    verification: str
    found: list[str]  # what the writer's search found
    source_chunk_ids: list[str]  # those chunks, so a reported card can be traced back to them
