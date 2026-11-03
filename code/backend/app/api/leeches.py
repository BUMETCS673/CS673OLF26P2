"""Leech Doctor routes.

    GET  /api/leech-suggestions                 -> 200 {processing, ready}. Also drives the queue.
    GET  /api/decks/<deck_id>/leech-review      -> 200 {review}, the deck's pending review or null
    POST /api/leech-reviews/<review_id>/decisions
         {decisions: [{card_id, option}]}       -> 200 the applied review

`option` is an option's index, "remove", or null to keep the card as it is.
"""

import logging

from flask import Blueprint, current_app, jsonify
from flask_login import current_user, login_required

from app.ai.checkpoints import discard_threads, open_checkpointer
from app.ai.leech import REPLACING_KINDS, resume_review
from app.api.decks import own_deck_or_404
from app.errors import ApiError, json_object, not_found, validation_error
from app.extensions import db
from app.leech_jobs import mark_handled, refresh_queue
from app.models import Card, Deck, LeechReview, utcnow
from app.models.leech_review import COMPLETED, PENDING

logger = logging.getLogger(__name__)

leeches_bp = Blueprint("leeches", __name__)

REMOVE = "remove"
BAD_DECISIONS = "decisions must list each recommended card once, with a valid option."


@leeches_bp.get("/leech-suggestions")
@login_required
def list_suggestions():
    processing = refresh_queue(current_user.id)
    rows = (
        db.session.query(LeechReview, Deck.name)
        .join(Deck, Deck.id == LeechReview.deck_id)
        .filter(LeechReview.user_id == current_user.id, LeechReview.status == PENDING)
        .order_by(LeechReview.id)
        .all()
    )
    return jsonify({
        "processing": processing,
        "ready": [
            {
                "review_id": review.id,
                "deck_id": review.deck_id,
                "deck_name": name,
                "card_count": len(review.recommendations),
            }
            for review, name in rows
        ],
    }), 200


@leeches_bp.get("/decks/<int:deck_id>/leech-review")
@login_required
def get_deck_review(deck_id):
    deck = own_deck_or_404(deck_id)
    review = LeechReview.query.filter_by(deck_id=deck.id, status=PENDING).first()
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
        valid = option is None or option == REMOVE or (
            type(option) is int and 0 <= option < len(options_by_card[card_id])
        )
        if not valid:
            raise validation_error(BAD_DECISIONS, field="decisions")
        seen.add(card_id)
    if seen != set(options_by_card):
        raise validation_error(BAD_DECISIONS, field="decisions")
    return [{"card_id": item["card_id"], "option": item["option"]} for item in decisions]


def _apply(review: LeechReview, decisions: list[dict]) -> tuple[list[dict], list[Card]]:
    """Change the deck to match the decisions. New cards start as new, with no lapses."""
    options_by_card = {item["card_id"]: item["options"] for item in review.recommendations}
    ids = [decision["card_id"] for decision in decisions]
    cards = {
        card.id: card
        for card in Card.query.filter(Card.deck_id == review.deck_id, Card.id.in_(ids))
    }
    applied, created = [], []
    for decision in decisions:
        card_id, choice = decision["card_id"], decision["option"]
        card = cards.get(card_id)  # None if the learner deleted it while the review was pending
        new_cards = []
        kind = None
        if card is not None and choice == REMOVE:
            kind = REMOVE
            db.session.delete(card)
        elif card is not None and choice is not None:
            option = options_by_card[card_id][choice]
            kind = option["kind"]
            new_cards = [
                Card(deck_id=review.deck_id, front=item["front"], back=item["back"], origin="ai")
                for item in option["cards"]
            ]
            db.session.add_all(new_cards)
            if kind in REPLACING_KINDS:
                db.session.delete(card)
            else:
                mark_handled(card)
        elif card is not None:
            mark_handled(card)
        created.extend(new_cards)
        applied.append({"card_id": card_id, "kind": kind, "new_cards": new_cards})
    db.session.flush()  # assigns the new cards' ids
    return [
        {
            "card_id": item["card_id"],
            "kind": item["kind"],
            "new_card_ids": [new.id for new in item["new_cards"]],
        }
        for item in applied
    ], created


@leeches_bp.post("/leech-reviews/<int:review_id>/decisions")
@login_required
def decide(review_id):
    # The lock makes two submissions run one after the other. SQLite ignores it.
    review = (
        LeechReview.query.filter_by(id=review_id, user_id=current_user.id)
        .with_for_update()
        .first()
    )
    if review is None:
        raise not_found("Review not found.")
    if review.status != PENDING:
        raise ApiError(409, "This review has already been completed.")
    decisions = _valid_decisions(json_object(), review)

    # The database is the record of what happened, so it commits first. If the commit fails the
    # run is still paused and the learner can retry. If finishing the run fails, the deck is
    # already right, and only a leftover checkpoint remains.
    applied, created = _apply(review, decisions)
    review.decisions = applied
    review.status = COMPLETED
    review.completed_at = utcnow()
    thread_id = review.thread_id
    db.session.commit()
    url = current_app.config["SQLALCHEMY_DATABASE_URI"]
    try:
        with open_checkpointer(url) as checkpointer:
            resume_review(checkpointer, thread_id, decisions)
    except Exception as error:
        logger.warning("leech_doctor outcome=resume_failed type=%s", type(error).__name__)
    discard_threads(url, [thread_id])
    return jsonify({
        "review": review.to_dict(),
        "cards": [card.to_dict() for card in created],
    }), 200
