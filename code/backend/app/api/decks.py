"""Deck endpoints - WS2 (Von).

The blueprint is registered by `app/api/__init__.py`; routes here appear
under /api/decks.

Every Deck carries `due_counts`: how many cards GET /api/decks/<id>/due would
serve right now, worked out from the same conditions (B2, decision P4).

    GET    /api/decks          -> 200 [Deck]
    POST   /api/decks          {name, description?}   -> 201 Deck
    GET    /api/decks/<id>     -> 200 Deck
    GET    /api/decks/<id>/due -> 200 {learning, review, new}
    PATCH  /api/decks/<id>     {name?, description?}  -> 200 Deck
    DELETE /api/decks/<id>     -> 204

Every route needs @login_required and every query is filtered by the
logged-in user, so someone else's deck answers 404, never 403.
"""

# B2: _due_conditions(), _due_counts(), _deck_json(), and due_counts on the four Deck routes.
# AI Utilization: ~100% of that code
# AI Tools Used: Devin (Cognition AI)
# AI-Assisted Activities:
#   API endpoint development
#   Documentation
# Human role: requirements (B2 in code/plans/FINALIZE_ITERATION_2_PLAN.md), direction,
# and review by Nurzat Mukhamedali.

from flask import Blueprint, jsonify
from flask_login import current_user, login_required
from sqlalchemy import and_, case, func, select

from app.errors import json_object, not_found, validation_error
from app.extensions import db
from app.models import Card, Deck, utcnow
from app.scheduler import LEARN_AHEAD, NEW_CARDS_PER_SESSION, REVIEWS_PER_SESSION, CardState

decks_bp = Blueprint("decks", __name__, url_prefix="/decks")

NAME_MAX = 120
DESCRIPTION_MAX = 1000


def _own_deck_or_404(deck_id: int) -> Deck:
    deck = Deck.query.filter_by(id=deck_id, user_id=current_user.id).first()
    if deck is None:
        raise not_found("Deck not found")
    return deck


def _valid_name(value) -> str:
    if not isinstance(value, str) or not value.strip():
        raise validation_error("name is required", field="name")
    value = value.strip()
    if len(value) > NAME_MAX:
        raise validation_error(
            f"name must be at most {NAME_MAX} characters", field="name"
        )
    return value


def _valid_description(value):
    # description is optional and may be cleared with null.
    if value is None:
        return None
    if not isinstance(value, str):
        raise validation_error("description must be a string", field="description")
    if len(value) > DESCRIPTION_MAX:
        raise validation_error(
            f"description must be at most {DESCRIPTION_MAX} characters",
            field="description",
        )
    return value


def _due_conditions(now):
    """One SQL condition per list GET /due serves. The counts use these too, so they agree."""
    return {
        "learning": and_(
            Card.state.in_((CardState.LEARNING, CardState.RELEARNING)),
            Card.due_at <= now + LEARN_AHEAD,
        ),
        "review": and_(Card.state == CardState.REVIEW, Card.due_at <= now),
        "new": Card.state == CardState.NEW,
    }


_SESSION_CAPS = {"review": REVIEWS_PER_SESSION, "new": NEW_CARDS_PER_SESSION}


def _due_counts(deck_ids, now) -> dict[int, dict[str, int]]:
    """`due_counts` for each deck in `deck_ids`, in one grouped query however many there are."""
    conditions = _due_conditions(now)
    counts = {deck_id: dict.fromkeys(conditions, 0) for deck_id in deck_ids}
    if not counts:
        return counts

    rows = db.session.execute(
        select(
            Card.deck_id,
            *(
                func.sum(case((condition, 1), else_=0)).label(name)
                for name, condition in conditions.items()
            ),
        )
        .where(Card.deck_id.in_(counts))
        .group_by(Card.deck_id)
    )
    # A deck with no cards has no row, so it keeps its zeros.
    for row in rows:
        values = row._mapping
        counts[row.deck_id] = {
            name: min(int(values[name] or 0), _SESSION_CAPS.get(name, float("inf")))
            for name in conditions
        }
    return counts


def _deck_json(deck: Deck, now) -> dict:
    return {**deck.to_dict(), "due_counts": _due_counts([deck.id], now)[deck.id]}


@decks_bp.get("")
@login_required
def list_decks():
    decks = (
        Deck.query.filter_by(user_id=current_user.id)
        .order_by(Deck.id)
        .all()
    )
    counts = _due_counts([deck.id for deck in decks], utcnow())
    return jsonify([{**deck.to_dict(), "due_counts": counts[deck.id]} for deck in decks]), 200


@decks_bp.post("")
@login_required
def create_deck():
    body = json_object()
    name = _valid_name(body.get("name"))
    description = _valid_description(body.get("description"))

    deck = Deck(user_id=current_user.id, name=name, description=description)
    db.session.add(deck)
    db.session.commit()
    return jsonify(_deck_json(deck, utcnow())), 201


@decks_bp.get("/<int:deck_id>")
@login_required
def get_deck(deck_id):
    return jsonify(_deck_json(_own_deck_or_404(deck_id), utcnow())), 200


@decks_bp.get("/<int:deck_id>/due")
@login_required
def get_due_cards(deck_id):
    """Return this deck's learning, due review, and new cards for a session."""
    _own_deck_or_404(deck_id)
    now = utcnow()
    conditions = _due_conditions(now)
    cards = Card.query.filter_by(deck_id=deck_id)
    learning = (
        cards.filter(conditions["learning"])
        .order_by(Card.due_at, Card.id)
        .all()
    )
    review = (
        cards.filter(conditions["review"])
        .order_by(Card.due_at, Card.id)
        .limit(REVIEWS_PER_SESSION)
        .all()
    )
    new = (
        cards.filter(conditions["new"])
        .order_by(Card.id)
        .limit(NEW_CARDS_PER_SESSION)
        .all()
    )
    return jsonify({
        "learning": [card.to_study_dict(now) for card in learning],
        "review": [card.to_study_dict(now) for card in review],
        "new": [card.to_study_dict(now) for card in new],
    }), 200


@decks_bp.patch("/<int:deck_id>")
@login_required
def update_deck(deck_id):
    deck = _own_deck_or_404(deck_id)
    body = json_object()

    # Validate everything before changing anything.
    updates = {}
    if "name" in body:
        updates["name"] = _valid_name(body["name"])
    if "description" in body:
        updates["description"] = _valid_description(body["description"])

    for field, value in updates.items():
        setattr(deck, field, value)

    db.session.commit()
    return jsonify(_deck_json(deck, utcnow())), 200


@decks_bp.delete("/<int:deck_id>")
@login_required
def delete_deck(deck_id):
    deck = _own_deck_or_404(deck_id)
    # The database cascade removes the deck's cards.
    db.session.delete(deck)
    db.session.commit()
    return "", 204
