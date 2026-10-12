"""Accepting and rejecting AI suggestions - B4 (Von).

The blueprint is registered by `app/api/__init__.py`. Like `cards_bp`, it has no
url_prefix:

    POST /api/generations/<generation_id>/accept  {indexes}  -> 201 {cards: [Card], generation: Generation}
    POST /api/generations/<generation_id>/reject  {indexes}  -> 200 Generation

Contract C4 in code/plans/ITERATION_3_PLAN.md. Only accepting creates cards, and only it
sets `origin = "ai"` (rule 18). Someone else's generation answers 404.
Step 0a creates the blueprint with no routes, so B4 only ever touches this file.
"""

# Step 0a: the empty blueprint and the docstring.
# AI Utilization: ~100% of that code
# AI Tools Used: Claude Code (Claude Opus 5.5)
# AI-Assisted Activities:
#   Blueprint scaffolding
#   Documentation
# Human role: plan approval, code review, and hands-on testing by Miles Cameron.

#
# B4: the accept and reject routes.
# AI Utilization: 90%
# AI Tools Used: Claude
# AI-Assisted Activities:
#   - API endpoint development
#   - Input validation
# Human role: ran the tests locally and in Docker, checked them against the plan, and
# opened the PR, by Osasenaga Von Okunbor.

from flask import Blueprint, jsonify
from flask_login import current_user, login_required

from app.errors import json_object, not_found, validation_error
from app.extensions import db
from app.models import AiGeneration, Card

generations_bp = Blueprint("generations", __name__)

PENDING = "pending"
ACCEPTED = "accepted"
REJECTED = "rejected"
BAD_INDEXES = "indexes must be a non-empty list of card positions."


def _own_generation_or_404(generation_id: int, lock: bool = False) -> AiGeneration:
    """The logged-in user's generation, or 404 (security addition 6).

    With `lock`, the row is locked until the transaction ends, so two accepts that arrive
    together run one after the other. Postgres honors it; SQLite ignores the clause.
    """
    query = AiGeneration.query.filter_by(id=generation_id, user_id=current_user.id)
    if lock:
        query = query.with_for_update()
    generation = query.first()
    if generation is None:
        raise not_found("Generation not found.")
    return generation


def _valid_indexes(body: dict, count: int) -> list[int]:
    """The positions in the body, repeats removed, in index order. 422 for anything else."""
    indexes = body.get("indexes")
    if not isinstance(indexes, list) or not indexes:
        raise validation_error(BAD_INDEXES, field="indexes")
    for index in indexes:
        # bool is a subclass of int, so True would otherwise pass as 1.
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < count:
            raise validation_error(BAD_INDEXES, field="indexes")
    return sorted(set(indexes))


def _decide(generation: AiGeneration, indexes: list[int], status: str) -> list[int]:
    """Set `status` on each pending index, and return the indexes that changed.

    Decisions are final, so an index that's already accepted or rejected is skipped.
    The new list is assigned rather than edited in place, or it's never saved (rule 20).
    """
    changed = [i for i in indexes if generation.candidates[i]["status"] == PENDING]
    generation.candidates = [
        {**candidate, "status": status} if i in changed else dict(candidate)
        for i, candidate in enumerate(generation.candidates)
    ]
    return changed


@generations_bp.post("/generations/<int:generation_id>/accept")
@login_required
def accept(generation_id):
    # Ownership before the body (C4), so a stranger learns nothing from a 422.
    generation = _own_generation_or_404(generation_id, lock=True)
    indexes = _valid_indexes(json_object(), len(generation.candidates))

    accepted = _decide(generation, indexes, ACCEPTED)
    cards = [
        Card(
            deck_id=generation.deck_id,
            front=generation.candidates[i]["front"],
            back=generation.candidates[i]["back"],
            origin="ai",
            generation_id=generation.id,
        )
        for i in accepted
    ]
    db.session.add_all(cards)
    db.session.commit()
    return jsonify(
        {
            "cards": [card.to_dict() for card in cards],
            "generation": generation.to_dict(),
        }
    ), 201


@generations_bp.post("/generations/<int:generation_id>/reject")
@login_required
def reject(generation_id):
    generation = _own_generation_or_404(generation_id, lock=True)
    indexes = _valid_indexes(json_object(), len(generation.candidates))

    _decide(generation, indexes, REJECTED)
    db.session.commit()
    return jsonify(generation.to_dict()), 200
