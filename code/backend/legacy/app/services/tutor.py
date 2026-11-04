"""The deck tutor: budgets, one conversation per deck, running turns, and applying proposals."""

import logging
import uuid
from datetime import timedelta

from flask import current_app
from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import IntegrityError

from app.ai.checkpoints import discard_threads, open_checkpointer
from app.ai.cleanup import clean_drafts
from app.ai.provider import AIUnavailable, Role, get_provider
from app.ai.tutor import (
    MAX_MESSAGES,
    TURN_COST,
    TURN_MAX_CALLS,
    TUTOR_PROMPT_VERSION,
    read_messages,
    resume_turn,
    run_turn,
)
from app.extensions import db
from app.models import Card, Deck, TutorConversation, utcnow
from app.models.tutor import AWAITING_DECISION, IDLE, REPLYING
from app.services.errors import BudgetExceeded, Conflict, InvalidRequest, NotAvailable
from app.services.usage import TUTOR, feature_calls, record_usage, within_model_limits

logger = logging.getLogger(__name__)

STALE_AFTER = timedelta(minutes=5)  # a reply older than this counts as lost
TURNED_OFF = "The tutor isn't available right now."
SITE_LIMIT = "The tutor has hit today's limit for the whole site. Try again later."
USER_LIMIT = "You've reached today's limit for the tutor. Try again later."


def _database_url() -> str:
    return current_app.config["SQLALCHEMY_DATABASE_URI"]


def conversation_for(deck: Deck) -> TutorConversation | None:
    return TutorConversation.query.filter_by(deck_id=deck.id).first()


def view(conversation: TutorConversation | None) -> dict:
    """What the learner sees of a conversation."""
    messages = []
    if conversation is not None:
        with open_checkpointer(_database_url()) as checkpointer:
            messages = read_messages(checkpointer, conversation.thread_id)
    return {
        "enabled": current_app.config["AI_TUTOR_ENABLED"],
        "status": conversation.status if conversation else IDLE,
        # Tool results are internal, so the learner only sees the conversation itself.
        "messages": [
            {"role": item["role"], "text": item["text"], "error": bool(item.get("error"))}
            for item in messages
            if item["role"] in ("user", "tutor")
        ],
        "proposal": conversation.pending_proposal if conversation else None,
    }


def _check_budgets(user_id: int) -> None:
    """Reserve a turn's worst case against the site's and the learner's rolling budgets."""
    config = current_app.config
    if feature_calls(TUTOR) + TURN_MAX_CALLS > config["AI_TUTOR_DAILY_LIMIT"]:
        raise BudgetExceeded(SITE_LIMIT)
    if feature_calls(TUTOR, user_id) + TURN_MAX_CALLS > config["AI_TUTOR_USER_DAILY_LIMIT"]:
        raise BudgetExceeded(USER_LIMIT)
    if not within_model_limits(TURN_COST):
        raise BudgetExceeded(SITE_LIMIT)


def _get_or_create(deck: Deck, user_id: int) -> TutorConversation:
    conversation = conversation_for(deck)
    if conversation is not None:
        return conversation
    conversation = TutorConversation(
        user_id=user_id, deck_id=deck.id, thread_id=str(uuid.uuid4())
    )
    db.session.add(conversation)
    try:
        db.session.commit()
    except IntegrityError:  # a simultaneous request created it first
        db.session.rollback()
        return conversation_for(deck)
    return conversation


def _claim(conversation: TutorConversation) -> bool:
    """Move idle to replying. The conditional update lets only one request succeed."""
    now = utcnow()
    result = db.session.execute(
        update(TutorConversation)
        .where(
            TutorConversation.id == conversation.id,
            or_(
                TutorConversation.status == IDLE,
                and_(
                    TutorConversation.status == REPLYING,
                    TutorConversation.status_at < now - STALE_AFTER,
                ),
            ),
        )
        .values(status=REPLYING, status_at=now)
        .execution_options(synchronize_session=False)
    )
    db.session.commit()
    return result.rowcount == 1


def _release(conversation_id: int) -> None:
    db.session.rollback()
    conversation = db.session.get(TutorConversation, conversation_id)
    conversation.status = IDLE
    conversation.status_at = utcnow()
    db.session.commit()


def send_message(deck: Deck, user_id: int, text: str) -> TutorConversation:
    """Run one turn of the chat, and save what it produced."""
    if not current_app.config["AI_TUTOR_ENABLED"]:
        raise NotAvailable(TURNED_OFF)
    _check_budgets(user_id)
    try:
        provider, judge = get_provider(), get_provider(Role.JUDGE)
    except AIUnavailable as error:
        raise NotAvailable(error.message) from None

    conversation = _get_or_create(deck, user_id)
    if conversation.status == AWAITING_DECISION:
        raise Conflict("Add or decline the suggested cards first.")
    if conversation.message_count >= MAX_MESSAGES:
        raise InvalidRequest("This chat is full. Reset it to keep going.", field="text")
    if not _claim(conversation):
        raise Conflict("The tutor is still replying.")

    # Only this deck's cards are loaded, which is all the agent's tools can ever read.
    cards = [
        {"front": row.front, "back": row.back, "lapses": row.lapses}
        for row in db.session.execute(
            select(Card.front, Card.back, Card.lapses).where(Card.deck_id == deck.id)
        )
    ]
    conversation_id, thread_id = conversation.id, conversation.thread_id
    deck_id, deck_name = deck.id, deck.name
    db.session.commit()
    try:
        with open_checkpointer(_database_url()) as checkpointer:
            outcome = run_turn(provider, judge, checkpointer, thread_id, text, deck_name, cards)
    except Exception as error:
        # The type only: the text can contain learner content.
        logger.warning("deck_tutor outcome=turn_error type=%s", type(error).__name__)
        _release(conversation_id)
        # Any calls made before the failure still spent quota.
        record_usage(TUTOR, user_id, deck_id, provider, judge, TUTOR_PROMPT_VERSION)
        db.session.commit()
        raise NotAvailable("The tutor didn't respond. Try again in a minute.") from None

    conversation = db.session.get(TutorConversation, conversation_id)
    conversation.message_count = len(outcome.messages)
    conversation.status = AWAITING_DECISION if outcome.proposal else IDLE
    conversation.status_at = utcnow()
    conversation.pending_proposal = (
        {**outcome.proposal, "verification": outcome.verification} if outcome.proposal else None
    )
    record_usage(TUTOR, user_id, deck_id, provider, judge, TUTOR_PROMPT_VERSION)
    db.session.commit()
    return conversation


def decide_proposal(deck: Deck, proposal_id: object, accept: bool) -> TutorConversation:
    """Add or decline the cards waiting for a decision."""
    # The lock, the status and the id tie this approval to one proposal, and use it once.
    conversation = (
        TutorConversation.query.filter_by(deck_id=deck.id).with_for_update().first()
    )
    proposal = conversation.pending_proposal if conversation else None
    if (
        proposal is None
        or conversation.status != AWAITING_DECISION
        or proposal_id != proposal["id"]
    ):
        raise Conflict("Those suggested cards are no longer waiting for a decision.")

    added = 0
    if accept:
        # Cards come from the server's copy, and the deck may have changed since.
        fronts = db.session.scalars(select(Card.front).where(Card.deck_id == deck.id)).all()
        drafts = clean_drafts(proposal["cards"], len(proposal["cards"]), fronts)
        db.session.add_all(
            Card(deck_id=deck.id, front=draft.front, back=draft.back, origin="ai")
            for draft in drafts
        )
        added = len(drafts)
    conversation.pending_proposal = None
    conversation.status = IDLE
    conversation.status_at = utcnow()
    conversation.message_count += 1
    thread_id = conversation.thread_id
    db.session.commit()

    # The database is the record of what happened, so it commits first. A failure here only
    # leaves the closing message out of the chat, and the next message starts a new turn.
    text = (
        f"Added {added} {'card' if added == 1 else 'cards'} to your deck." if accept
        else "Okay, I won't add those."
    )
    try:
        with open_checkpointer(_database_url()) as checkpointer:
            resume_turn(checkpointer, thread_id, text)
    except Exception as error:
        logger.warning("deck_tutor outcome=resume_failed type=%s", type(error).__name__)
    return conversation


def reset(deck: Deck) -> None:
    """Delete the deck's chat and its saved history."""
    conversation = conversation_for(deck)
    if conversation is None:
        return
    if conversation.status == REPLYING:
        raise Conflict("The tutor is still replying.")
    thread_id = conversation.thread_id
    db.session.delete(conversation)
    db.session.commit()
    discard_threads(_database_url(), [thread_id])
