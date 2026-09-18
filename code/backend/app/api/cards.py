"""Card endpoints — WS2 (Von).

The blueprint is registered by `app/api/__init__.py`. It has no url_prefix because the
card endpoints live under two different paths:

    GET    /api/decks/<deck_id>/cards  -> 200 [Card]
    POST   /api/decks/<deck_id>/cards  {front, back}   -> 201 Card
    PATCH  /api/cards/<card_id>        {front?, back?} -> 200 Card
    DELETE /api/cards/<card_id>        -> 204

@login_required on all four. A card is yours only if its deck is yours, so check
ownership by joining through the deck rather than trusting the card id:

    card = Card.query.join(Deck).filter(
        Card.id == card_id, Deck.user_id == current_user.id
    ).first()

Deleting a deck already deletes its cards — the database cascade handles it, so don't
write a loop for that.
"""

from flask import Blueprint

cards_bp = Blueprint("cards", __name__)

# TODO(WS2): the four endpoints above.
