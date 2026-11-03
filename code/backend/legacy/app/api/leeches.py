"""Leech Doctor routes.

    POST /api/leech-suggestions/refresh         -> 200 {processing, ready}. Drives the queue, so
                                                   it's a POST: it can start AI spending.
    GET  /api/decks/<deck_id>/leech-review      -> 200 {review}, the deck's pending review or null
    POST /api/leech-reviews/<review_id>/decisions
         {decisions: [{card_id, option}]}       -> 200 the applied review

`option` is an option's index, "remove", or null to keep the card as it is.
"""

from flask import Blueprint, jsonify
from flask_login import current_user, login_required

from app.api.decks import own_deck_or_404
from app.errors import ApiError, json_object, not_found, validation_error
from app.models import LeechReview
from app.models.leech_review import PENDING
from app.services import leech_reviews

leeches_bp = Blueprint("leeches", __name__)

BAD_DECISIONS = "decisions must list each recommended card once, with a valid option."


@leeches_bp.post("/leech-suggestions/refresh")
@login_required
def refresh_suggestions():
    return jsonify(leech_reviews.refresh_suggestions(current_user.id)), 200


@leeches_bp.get("/decks/<int:deck_id>/leech-review")
@login_required
def get_deck_review(deck_id):
    review = leech_reviews.pending_review(own_deck_or_404(deck_id))
    return jsonify({"review": review.to_dict() if review else None}), 200


def _valid_decisions(body: dict, review: LeechReview) -> list[dict]:
    """The body's decisions, covering each recommended card exactly once. 422 otherwise."""
    decisions = body.get("decisions")
    if not isinstance(decisions, list):
        raise validation_error(BAD_DECISIONS, field="decisions")
    options_by_card = {item["card_id"]: item["options"] for item in review.recommendations}
    seen = set()
    for decision in decisions:
        if not isinstance(decision, dict):
            raise validation_error(BAD_DECISIONS, field="decisions")
        card_id, option = decision.get("card_id"), decision.get("option")
        # type() rejects bools, and values like lists that can't be looked up in a dict.
        if type(card_id) is not int or card_id not in options_by_card or card_id in seen:
            raise validation_error(BAD_DECISIONS, field="decisions")
        valid = option is None or option == leech_reviews.REMOVE or (
            type(option) is int and 0 <= option < len(options_by_card[card_id])
        )
        if not valid:
            raise validation_error(BAD_DECISIONS, field="decisions")
        seen.add(card_id)
    if seen != set(options_by_card):
        raise validation_error(BAD_DECISIONS, field="decisions")
    return [{"card_id": item["card_id"], "option": item["option"]} for item in decisions]


@leeches_bp.post("/leech-reviews/<int:review_id>/decisions")
@login_required
def decide(review_id):
    review = leech_reviews.lock_own_review(review_id, current_user.id)
    if review is None:
        raise not_found("Review not found.")
    if review.status != PENDING:
        raise ApiError(409, "This review has already been completed.")
    created = leech_reviews.apply_decisions(review, _valid_decisions(json_object(), review))
    return jsonify({
        "review": review.to_dict(),
        "cards": [card.to_dict() for card in created],
    }), 200
