"""Card endpoints - WS2 (Von).

The blueprint is registered by `app/api/__init__.py`. It has no url_prefix
because the card endpoints live under two different paths:

    GET    /api/decks/<deck_id>/cards  -> 200 [Card]
    POST   /api/decks/<deck_id>/cards  {front, back}     -> 201 Card
    PATCH  /api/cards/<card_id>        {front?, back?}   -> 200 Card
    DELETE /api/cards/<card_id>        -> 204

A card is yours only if its deck is yours, so ownership is checked by
joining through the deck. Someone else's card answers 404.
"""

from flask import Blueprint, jsonify
from flask_login import current_user, login_required

from app.errors import json_object, not_found, validation_error
from app.extensions import db
from app.models import Card, Deck

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
