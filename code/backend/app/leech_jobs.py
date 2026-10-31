"""The Leech Doctor queue: creates reviews for flagged cards and runs them in the background.

Page loads and status checks drive the queue through `refresh_queue()`, because the free tier has
no scheduler. A job lost to a restart is therefore retried on a later request.

    queued -> running -> pending -> completed
      ^          |
      +- retry --+-> failed (second failure)

A failed call retries after RETRY_AFTER. A rate-limited call also waits, but uses no attempt,
because the cards aren't at fault. Budgets bound how often that can repeat.
"""

import logging
import threading
import uuid
from datetime import datetime, timedelta

from flask import current_app
from sqlalchemy import and_, func, or_, select, update

from app.ai.checkpoints import discard_threads, open_checkpointer
from app.ai.leech import MAX_CARDS_PER_REVIEW, similar_cards, start_review
from app.ai.provider import AIUnavailable, get_provider
from app.ai_usage import CAP_WINDOW, site_model_calls
from app.extensions import db
from app.models import Card, Deck, LeechReview, as_utc, utcnow
from app.models.leech_review import ACTIVE, COMPLETED, FAILED, PENDING, QUEUED, RUNNING

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 2
JOB_CALLS = 2  # one to diagnose and one to judge, reserved against the budgets before starting
REFLAG_AFTER = 2 # lapses until a handled card is flagged again
RETRY_AFTER = timedelta(minutes=10)  # wait before retrying a failed or rate-limited job
STALE_AFTER = timedelta(minutes=5)   # a running job older than this counts as lost
DISMISS_PAUSE = timedelta(days=7)    # no new review after the learner dismisses everything
MAX_CONCURRENT_JOBS = 2              # per worker, because each holds a thread and connections

_job_slots = threading.BoundedSemaphore(MAX_CONCURRENT_JOBS)


def flagged_cards(deck_id: int) -> list[Card]:
    """The deck's flagged cards, most lapses first."""
    return (
        Card.query.filter(Card.deck_id == deck_id, Card.lapses >= Card.leech_next_at)
        .order_by(Card.lapses.desc(), Card.id)
        .all()
    )


def mark_handled(card: Card) -> None:
    """Stop flagging `card` until it lapses again."""
    card.leech_next_at = card.lapses + REFLAG_AFTER


def _leech_calls(*conditions) -> int:
    return db.session.scalar(
        select(func.coalesce(func.sum(LeechReview.model_calls), 0)).where(
            LeechReview.created_at > utcnow() - CAP_WINDOW, *conditions
        )
    )


def _can_run(user_id: int) -> bool:
    """Whether a job could make its AI call now. Otherwise jobs wait in the queue."""
    config = current_app.config
    # Background work stops early, so that it can't use up the quota for generating cards.
    usable = config["AI_SITE_DAILY_LIMIT"] - config["AI_LEECH_SITE_RESERVE"]
    if (
        site_model_calls() + JOB_CALLS > usable
        or _leech_calls() + JOB_CALLS > config["AI_LEECH_DAILY_LIMIT"]
        or _leech_calls(LeechReview.user_id == user_id) + JOB_CALLS
        > config["AI_LEECH_USER_DAILY_LIMIT"]
    ):
        return False
    try:
        get_provider()
        get_provider("judge")
    except AIUnavailable:
        return False
    return True


def _is_paused(deck_id: int) -> bool:
    """True when the deck's last review was dismissed entirely within the pause window."""
    last = (
        LeechReview.query.filter_by(deck_id=deck_id, status=COMPLETED)
        .order_by(LeechReview.completed_at.desc())
        .first()
    )
    if last is None or not last.decisions:
        return False
    return (
        all(decision["kind"] is None for decision in last.decisions)
        and as_utc(last.completed_at) > utcnow() - DISMISS_PAUSE
    )


def _ensure_reviews(user_id: int) -> None:
    """Queue a review for each of the user's decks with flagged cards and no active review."""
    deck_ids = db.session.scalars(
        select(Card.deck_id)
        .join(Deck, Deck.id == Card.deck_id)
        .where(Deck.user_id == user_id, Card.lapses >= Card.leech_next_at)
        .distinct()
    ).all()
    for deck_id in deck_ids:
        # The lock stops two simultaneous requests from queuing two reviews. SQLite ignores it.
        db.session.scalar(select(Deck.id).where(Deck.id == deck_id).with_for_update())
        active = LeechReview.query.filter(
            LeechReview.deck_id == deck_id, LeechReview.status.in_(ACTIVE)
        ).first()
        if active is None and not _is_paused(deck_id):
            db.session.add(LeechReview(user_id=user_id, deck_id=deck_id, status=QUEUED))
        db.session.commit()


def _start_thread(review_id: int) -> None:
    if current_app.config["AI_LEECH_RUN_INLINE"]:
        run_job(review_id)
        return
    # With no free slot the job stays queued, and a later request starts it.
    if not _job_slots.acquire(blocking=False):
        return
    app = current_app._get_current_object()

    def target():
        try:
            with app.app_context():
                run_job(review_id)
        finally:
            _job_slots.release()

    threading.Thread(target=target, daemon=True).start()


def _startable(now: datetime):
    """Rows a job may claim: queued and past any retry wait, or running but lost."""
    return or_(
        and_(
            LeechReview.status == QUEUED,
            or_(LeechReview.started_at.is_(None), LeechReview.started_at < now - RETRY_AFTER),
        ),
        and_(LeechReview.status == RUNNING, LeechReview.started_at < now - STALE_AFTER),
    )


def refresh_queue(user_id: int) -> bool:
    """Queue and start the user's jobs. Returns whether results may arrive soon."""
    if not current_app.config["AI_LEECH_ENABLED"]:
        return False
    _ensure_reviews(user_id)
    can_run = _can_run(user_id)
    if can_run:
        waiting = db.session.scalars(
            select(LeechReview.id).where(LeechReview.user_id == user_id, _startable(utcnow()))
        ).all()
        for review_id in waiting:
            _start_thread(review_id)

    # A job waiting on a retry or a budget won't finish soon, so the browser needn't keep checking.
    soon = LeechReview.status == RUNNING
    if can_run:
        soon = or_(soon, _startable(utcnow()))
    return db.session.scalar(
        select(func.count()).select_from(LeechReview).where(LeechReview.user_id == user_id, soon)
    ) > 0


def _claim(review_id: int) -> bool:
    """Move the row to running. The conditional update lets only one worker succeed."""
    now = utcnow()
    result = db.session.execute(
        update(LeechReview)
        .where(LeechReview.id == review_id, _startable(now))
        .values(
            status=RUNNING,
            attempts=LeechReview.attempts + 1,
            started_at=now,
            thread_id=str(uuid.uuid4()),
        )
        .execution_options(synchronize_session=False)
    )
    db.session.commit()
    return result.rowcount == 1


def _handle_cards(review: LeechReview, keep: set[int] = frozenset()) -> None:
    """Mark the review's cards as handled, except those in `keep`."""
    ids = [card_id for card_id in review.card_ids or [] if card_id not in keep]
    for card in Card.query.filter(Card.id.in_(ids)):
        mark_handled(card)


def _record_failure(review_id: int) -> None:
    review = db.session.get(LeechReview, review_id)
    if review.attempts < MAX_ATTEMPTS:
        review.status = QUEUED
    else:
        review.status = FAILED
        review.completed_at = utcnow()
        _handle_cards(review)
    db.session.commit()


def _diagnose(review: LeechReview):
    """Load the deck's flagged cards and run the graph. Returns None if none are flagged."""
    flagged = flagged_cards(review.deck_id)[:MAX_CARDS_PER_REVIEW]
    if not flagged:
        return None
    rows = db.session.execute(
        select(Card.id, Card.front, Card.back).where(Card.deck_id == review.deck_id)
    ).all()
    deck_cards = [{"id": row.id, "front": row.front, "back": row.back} for row in rows]
    cards = []
    for card in flagged:
        item = {"id": card.id, "front": card.front, "back": card.back, "lapses": card.lapses}
        cards.append({**item, "similar": similar_cards(item, deck_cards)})
    review.card_ids = [card["id"] for card in cards]
    thread_id = review.thread_id
    db.session.commit()

    provider, judge = get_provider(), get_provider("judge")
    with open_checkpointer(current_app.config["SQLALCHEMY_DATABASE_URI"]) as checkpointer:
        outcome = start_review(
            provider, judge, checkpointer, thread_id, cards,
            [item["front"] for item in deck_cards],
        )
    review.model = provider.name
    review.input_tokens += provider.usage.input_tokens
    review.output_tokens += provider.usage.output_tokens
    review.judge_model = judge.name
    review.judge_input_tokens += judge.usage.input_tokens
    review.judge_output_tokens += judge.usage.output_tokens
    review.model_calls += outcome.model_calls
    return outcome


def _save_results(review: LeechReview, outcome) -> None:
    review.recommendations = outcome.recommendations
    review.shared_cause = outcome.shared_cause
    review.verification = outcome.verification
    # A card with no usable fix gets no suggestion, and stays quiet until it lapses again.
    _handle_cards(review, keep={item["card_id"] for item in outcome.recommendations})
    review.status = PENDING if outcome.recommendations else COMPLETED
    if not outcome.recommendations:
        review.completed_at = utcnow()
    db.session.commit()


def run_job(review_id: int) -> None:
    """Claim a queued review and run it. Failures never leave this function."""
    review = db.session.get(LeechReview, review_id)
    if review is None or not _can_run(review.user_id) or not _claim(review_id):
        return
    review = db.session.get(LeechReview, review_id)
    thread_id = review.thread_id
    if review.attempts > MAX_ATTEMPTS:  # the last attempt was lost, so stop retrying
        _record_failure(review_id)
        return

    try:
        outcome = _diagnose(review)
    except Exception as error:
        # Broad, because a thread has no caller to report to. The type only, because the text
        # can contain learner content.
        logger.warning("leech_doctor outcome=job_error type=%s", type(error).__name__)
        db.session.rollback()
        _record_failure(review_id)
        paused = False
    else:
        if outcome is None:
            review.status = COMPLETED
            review.completed_at = utcnow()
            db.session.commit()
        elif outcome.rate_limited:
            review.attempts -= 1
            review.status = QUEUED
            db.session.commit()
        elif outcome.failed:
            db.session.commit()
            _record_failure(review_id)
        else:
            _save_results(review, outcome)
        paused = db.session.get(LeechReview, review_id).status == PENDING

    # Only a paused run needs its checkpoint.
    if not paused:
        discard_threads(current_app.config["SQLALCHEMY_DATABASE_URI"], [thread_id])
