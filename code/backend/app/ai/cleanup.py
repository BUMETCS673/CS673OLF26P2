"""Checking what the model sent back before a learner sees it (B1).

`clean_drafts()` follows "Cleaning what comes back", and `normalize_front()` follows C8, in
code/plans/ITERATION_3_PLAN.md.

Pure (rule 19): no Flask, no SQLAlchemy, no `app.models`.
"""

# Step 0a: the signatures.
# AI Utilization: ~100% of that code
# AI Tools Used: Claude Code (Claude Opus 5.5)
# AI-Assisted Activities:
#   Function signature stubs
# Human role: plan approval, code review, and hands-on testing by Miles Cameron.
#
# B1: normalize_front() and clean_drafts().
# AI Utilization: ~100% of that code
# AI Tools Used: Claude Code (Claude Opus 5.5)
# AI-Assisted Activities:
#   Output validation and normalization
#   Documentation
# Human role: plan review, code review, and CI verification by Duc Anh Nguyen.

import re
import unicodedata
from collections.abc import Iterable

from app.ai.provider import AIUnavailable, CardDraft

TEXT_MAX = 2000  # the same limit as a card's side in app/api/cards.py

# C8: whitespace and these marks come off both ends. Nothing else is removed.
_END_MARKS = " .,;:!?¿¡…'\"‘’“”«»()[]{}"
_WHITESPACE = re.compile(r"\s+")


def normalize_front(text: str) -> str:
    """C8's normalization rule (rule 22)."""
    text = unicodedata.normalize("NFC", text).lower()
    return _WHITESPACE.sub(" ", text).strip(_END_MARKS)


def _gives_answer_away(front: str, back: str) -> bool:
    """True when the normalized back appears in the normalized front as whole words."""
    return re.search(r"(?<!\w)" + re.escape(back) + r"(?!\w)", front) is not None


def clean_drafts(raw: object, count: int, existing_fronts: Iterable[str]) -> list[CardDraft]:
    """What the provider returned, made safe to show. Raises AIUnavailable when `raw` isn't a list."""
    if not isinstance(raw, list):
        raise AIUnavailable()

    seen = {normalize_front(front) for front in existing_fronts}
    kept: list[CardDraft] = []
    for item in raw:
        if len(kept) >= count:
            break
        if not isinstance(item, dict):
            continue
        front, back = item.get("front"), item.get("back")
        if not isinstance(front, str) or not isinstance(back, str):
            continue
        front, back = front.strip(), back.strip()
        if not front or not back or len(front) > TEXT_MAX or len(back) > TEXT_MAX:
            continue
        normal_front, normal_back = normalize_front(front), normalize_front(back)
        if not normal_back or _gives_answer_away(normal_front, normal_back):
            continue
        if normal_front in seen:
            continue
        seen.add(normal_front)
        kept.append(CardDraft(front=front, back=back))
    return kept
