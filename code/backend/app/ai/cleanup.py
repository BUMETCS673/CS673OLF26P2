"""Checking what the model sent back before a learner sees it (B1).

Step 0a writes the signatures, so B3 can import them from the start. B1 writes the
bodies, from "Cleaning what comes back" and C8 in code/plans/ITERATION_3_PLAN.md.

Pure (rule 19): no Flask, no SQLAlchemy, no `app.models`.
"""

# AI Utilization: ~100% of this file's code
# AI Tools Used: Claude Code (Claude Opus 5.5)
# AI-Assisted Activities:
#   Function signature stubs
# Human role: plan approval, code review, and hands-on testing by Miles Cameron.

from collections.abc import Iterable

from app.ai.provider import CardDraft


def normalize_front(text: str) -> str:
    """C8's normalization rule (rule 22)."""
    raise NotImplementedError("B1 writes normalize_front(). See code/plans/ITERATION_3_PLAN.md.")


def clean_drafts(raw: object, count: int, existing_fronts: Iterable[str]) -> list[CardDraft]:
    """What the provider returned, made safe to show. Raises AIUnavailable when `raw` isn't a list."""
    raise NotImplementedError("B1 writes clean_drafts(). See code/plans/ITERATION_3_PLAN.md.")
