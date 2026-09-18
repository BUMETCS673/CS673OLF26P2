"""Deck endpoints — WS2 (Von).

The blueprint is registered by `app/api/__init__.py`; add routes here and they appear
under /api/decks. Endpoints to build, from the API contract:

    GET    /api/decks          -> 200 [Deck]
    POST   /api/decks          {name, description?}   -> 201 Deck
    GET    /api/decks/<id>     -> 200 Deck
    PATCH  /api/decks/<id>     {name?, description?}  -> 200 Deck
    DELETE /api/decks/<id>     -> 204

Every one of them needs @login_required, and every query must be filtered by the
logged-in user (Security basics #3) — not `Deck.query.get(id)` but:

    deck = Deck.query.filter_by(id=deck_id, user_id=current_user.id).first()
    if deck is None:
        raise not_found("Deck not found")

Read request bodies with `json_object()` from app.errors -- not `request.get_json()`,
which answers a request without a JSON Content-Type with a 415 that isn't in the
contract:

    from app.errors import json_object, not_found, validation_error

    body = json_object()          # a dict, or raises the contract's 400

`Deck.to_dict()` already includes `card_count`, counted in SQL by the deck query
itself. Don't count cards in Python (`len(deck.cards)`) -- that loads every card of
every deck, one extra query each, which is what this endpoint exists to avoid.
"""

from flask import Blueprint

decks_bp = Blueprint("decks", __name__, url_prefix="/decks")

# TODO(WS2): the five endpoints above.
