"""Card endpoints - WS2 (Von), plus reviewing a card (Lab 3, Story 5).

The blueprint is registered by `app/api/__init__.py`. It has no url_prefix
because the card endpoints live under two different paths:

    GET    /api/decks/<deck_id>/cards   -> 200 [Card]
    POST   /api/decks/<deck_id>/cards   {front, back}     -> 201 Card
    PATCH  /api/cards/<card_id>         {front?, back?}   -> 200 Card
    DELETE /api/cards/<card_id>         -> 204
    POST   /api/cards/<card_id>/review  {rating}          -> 200 Card

A card is yours only if its deck is yours, so ownership is checked by
joining through the deck. Someone else's card answers 404.

Reviewing hands the card's schedule to `app.scheduler.answer_card()` and saves
what comes back. A card that isn't due yet answers 409 instead of being
rescheduled early (decision L7 in code/plans/LAB_3_PLAN.md).
"""

# Lab 3, Story 5: _is_due(), review_card(), and the review lines in the docstring.
# AI Utilization: ~100% of that code
# AI Tools Used: Claude Code (Claude Opus 5.5)
# AI-Assisted Activities:
#   API endpoint development
#   Documentation
# Human role: plan approval, code review, and hands-on testing by Miles Cameron.

from datetime import datetime

from flask import Blueprint, jsonify
from flask_login import current_user, login_required

from app.errors import conflict, json_object, not_found, validation_error
from app.extensions import db
from app.models import Card, Deck, utcnow
from app.scheduler import LEARN_AHEAD, CardSchedule, CardState, Rating, answer_card

cards_bp = Blueprint("cards", __name__)

TEXT_MAX = 2000


def _own_deck_or_404(deck_id: int) -> Deck:
    deck = Deck.query.filter_by(id=deck_id, user_id=current_user.id).first()
    if deck is None:
        raise not_found("Deck not found")
    return deck


def _own_card_or_404(card_id: int) -> Card:
    card = (
        Card.query.join(Deck)
        .filter(Card.id == card_id, Deck.user_id == current_user.id)
        .first()
    )
    if card is None:
        raise not_found("Card not found")
    return card


def _valid_text(body: dict, field: str) -> str:
    value = body.get(field)
    if not isinstance(value, str) or not value.strip():
        raise validation_error(f"{field} is required", field=field)
    value = value.strip()
    if len(value) > TEXT_MAX:
        raise validation_error(
            f"{field} must be at most {TEXT_MAX} characters", field=field
        )
    return value


def _is_due(schedule: CardSchedule, now: datetime) -> bool:
    """Whether the learner may answer this card now.

    New cards are always due. A learning or relearning card may be answered up to
    LEARN_AHEAD early, the way Anki shows one when nothing else is left to study.
    """
    if schedule.state is CardState.NEW:
        return True
    if schedule.state is CardState.REVIEW:
        return schedule.due_at <= now
    return schedule.due_at <= now + LEARN_AHEAD


@cards_bp.get("/decks/<int:deck_id>/cards")
@login_required
def list_cards(deck_id):
    deck = _own_deck_or_404(deck_id)
    cards = Card.query.filter_by(deck_id=deck.id).order_by(Card.id).all()
    return jsonify([card.to_dict() for card in cards]), 200


@cards_bp.post("/decks/<int:deck_id>/cards")
@login_required
def create_card(deck_id):
    deck = _own_deck_or_404(deck_id)
    body = json_object()
    front = _valid_text(body, "front")
    back = _valid_text(body, "back")

    card = Card(deck_id=deck.id, front=front, back=back)
    db.session.add(card)
    db.session.commit()
    return jsonify(card.to_dict()), 201


@cards_bp.patch("/cards/<int:card_id>")
@login_required
def update_card(card_id):
    card = _own_card_or_404(card_id)
    body = json_object()

    # Validate everything before changing anything.
    new_front = _valid_text(body, "front") if "front" in body else None
    new_back = _valid_text(body, "back") if "back" in body else None

    if new_front is not None:
        card.front = new_front
    if new_back is not None:
        card.back = new_back

    db.session.commit()
    return jsonify(card.to_dict()), 200


@cards_bp.delete("/cards/<int:card_id>")
@login_required
def delete_card(card_id):
    card = _own_card_or_404(card_id)
    db.session.delete(card)
    db.session.commit()
    return "", 204


@cards_bp.post("/cards/<int:card_id>/review")
@login_required
def review_card(card_id):
    # The checks run in the contract's order: ownership, body, rating, then due.
    card = _own_card_or_404(card_id)
    body = json_object()
    try:
        rating = Rating(body.get("rating"))
    except ValueError:
        raise validation_error(
            f"rating must be one of: {', '.join(Rating)}", field="rating"
        ) from None

    # One clock reading, so the due check and the scheduler agree on "now".
    now = utcnow()
    schedule = card.schedule
    if not _is_due(schedule, now):
        raise conflict("Card isn't due yet")

    card.schedule = answer_card(schedule, rating, now)
    db.session.commit()
    return jsonify(card.to_study_dict(now)), 200
