"""Deck tutor routes. Every one is limited to the signed-in user's deck.

    GET    /api/decks/<deck_id>/tutor            -> 200 the conversation
    POST   /api/decks/<deck_id>/tutor/messages   {text} -> 200 the conversation
    POST   /api/decks/<deck_id>/tutor/proposal   {proposal_id, accept} -> 200 the conversation
    DELETE /api/decks/<deck_id>/tutor            -> 204, and the saved chat is deleted
"""

from flask import Blueprint, jsonify
from flask_login import current_user, login_required

from app.api.decks import own_deck_or_404
from app.api.validation import required_text
from app.errors import json_object, validation_error
from app.services import tutor

tutor_bp = Blueprint("tutor", __name__)

MESSAGE_MAX = 2000


@tutor_bp.get("/decks/<int:deck_id>/tutor")
@login_required
def get_tutor(deck_id):
    return jsonify(tutor.view(tutor.conversation_for(own_deck_or_404(deck_id)))), 200


@tutor_bp.post("/decks/<int:deck_id>/tutor/messages")
@login_required
def send_message(deck_id):
    deck = own_deck_or_404(deck_id)
    text = required_text(json_object().get("text"), "text", MESSAGE_MAX)
    return jsonify(tutor.view(tutor.send_message(deck, current_user.id, text))), 200


@tutor_bp.post("/decks/<int:deck_id>/tutor/proposal")
@login_required
def decide_proposal(deck_id):
    deck = own_deck_or_404(deck_id)
    body = json_object()
    accept = body.get("accept")
    if not isinstance(accept, bool):
        raise validation_error("accept must be true or false.", field="accept")
    return jsonify(tutor.view(tutor.decide_proposal(deck, body.get("proposal_id"), accept))), 200


@tutor_bp.delete("/decks/<int:deck_id>/tutor")
@login_required
def reset_tutor(deck_id):
    tutor.reset(own_deck_or_404(deck_id))
    return "", 204
