"""What the graph's nodes share. Plain JSON-style values, since the checkpointer saves them."""

from typing import TypedDict


class ProblemCardState(TypedDict):
    # One per card with usable options:
    # {"card_id", "front", "back", "lapses", "options": [{"kind", "reason", "cards"}]}
    recommendations: list[dict]
    shared_cause: str | None  # only when at least two cards have recommendations
    verification: str
    decisions: list[dict]  # the learner's answer, once the run resumes
