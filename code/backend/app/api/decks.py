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

`Deck.to_dict()` already includes `card_count`.
"""

from flask import Blueprint

decks_bp = Blueprint("decks", __name__, url_prefix="/decks")

# TODO(WS2): the five endpoints above.
