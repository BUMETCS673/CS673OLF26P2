"""Deck endpoints - WS2 (Von).

The blueprint is registered by `app/api/__init__.py`; routes here appear
under /api/decks.

    GET    /api/decks          -> 200 [Deck]
    POST   /api/decks          {name, description?}   -> 201 Deck
    GET    /api/decks/<id>     -> 200 Deck
    PATCH  /api/decks/<id>     {name?, description?}  -> 200 Deck
    DELETE /api/decks/<id>     -> 204

Every route needs @login_required and every query is filtered by the
logged-in user, so someone else's deck answers 404, never 403.
"""

from flask import Blueprint, jsonify
from flask_login import current_user, login_required

from app.errors import json_object, not_found, validation_error
from app.extensions import db
from app.models import Deck

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


@decks_bp.get("")
@login_required
def list_decks():
    decks = (
        Deck.query.filter_by(user_id=current_user.id)
        .order_by(Deck.id)
        .all()
    )
    return jsonify([deck.to_dict() for deck in decks]), 200


@decks_bp.post("")
@login_required
def create_deck():
    body = json_object()
    name = _valid_name(body.get("name"))
    description = _valid_description(body.get("description"))

    deck = Deck(user_id=current_user.id, name=name, description=description)
    db.session.add(deck)
    db.session.commit()
    return jsonify(deck.to_dict()), 201


@decks_bp.get("/<int:deck_id>")
@login_required
def get_deck(deck_id):
    return jsonify(_own_deck_or_404(deck_id).to_dict()), 200


@decks_bp.patch("/<int:deck_id>")
@login_required
def update_deck(deck_id):
    deck = _own_deck_or_404(deck_id)
    body = json_object()

    # Validate everything before changing anything.
    if "name" in body:
        new_name = _valid_name(body["name"])
    if "description" in body:
        new_description = _valid_description(body["description"])

    if "name" in body:
        deck.name = new_name
    if "description" in body:
        deck.description = new_description

    db.session.commit()
    return jsonify(deck.to_dict()), 200


@decks_bp.delete("/<int:deck_id>")
@login_required
def delete_deck(deck_id):
    deck = _own_deck_or_404(deck_id)
    # The database cascade removes the deck's cards.
    db.session.delete(deck)
    db.session.commit()
    return "", 204
