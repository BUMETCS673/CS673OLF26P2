"""The deck tutor: budgets, one conversation per deck, running turns, and applying proposals.

A turn runs inside the request, since it only waits on the network and the page shows the reply
when it returns. No database transaction stays open while the model runs.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.cards.checks import clean_cards, normalized_fronts
from app.ai.checkpoints import discard_threads, open_checkpointer
from app.ai.models import (
    AIRateLimited,
    AIUnavailable,
    Role,
    ai_errors,
    load_chat_model,
    load_embeddings,
    model_name,
)
from app.ai.schemas import CardDraft
from app.ai.tracing import labelled_trace
from app.ai.tutor.context import TutorContext, no_similar_cards
from app.ai.tutor.graph import (
    MAX_MESSAGES,
    TURN_COST,
    TURN_MAX_CALLS,
    read_messages,
    resume_turn,
    run_turn,
)
from app.ai.tutor.prompts import TUTOR_PROMPT_VERSION
from app.ai.tutor.tools import MAX_TOOL_CARDS
from app.ai.usage import RunUsage
from app.core.errors import BudgetExceeded, Conflict, InvalidRequest, NotAvailable, NotFound
from app.core.settings import Settings
from app.models import Card, Deck, Job, TutorConversation, User, utcnow
from app.models.job import EMBED_CARDS
from app.models.tutor import AWAITING_DECISION, IDLE, REPLYING
from app.repositories.cards import CardRepository
from app.repositories.decks import DeckRepository
from app.repositories.jobs import JobRepository
from app.repositories.tutor import TutorRepository
from app.schemas.tutor import TutorView
from app.services.budget import TUTOR, BudgetService
from app.services.decks import DECK_NOT_FOUND

logger = logging.getLogger(__name__)

STALE_AFTER = timedelta(minutes=5)  # a reply older than this counts as lost
TURNED_OFF = "The tutor isn't available right now."
SITE_LIMIT = "The tutor has hit today's limit for the whole site. Try again later."
USER_LIMIT = "You've reached today's limit for the tutor. Try again later."
NO_REPLY = "The tutor didn't respond. Try again in a minute."
STILL_REPLYING = "The tutor is still replying."


class TutorService:
    def __init__(
        self,
        session: AsyncSession,
        conversations: TutorRepository,
        decks: DeckRepository,
        cards: CardRepository,
        jobs: JobRepository,
        budget: BudgetService,
        settings: Settings,
    ):
        self.session = session
        self.conversations = conversations
        self.decks = decks
        self.cards = cards
        self.jobs = jobs
        self.budget = budget
        self.settings = settings

    async def _owned_deck(self, deck_id: int, user: User) -> Deck:
        deck = await self.decks.get_owned(deck_id, user.id)
        if deck is None:
            raise NotFound(DECK_NOT_FOUND)
        return deck

    def _view(self, conversation: TutorConversation | None, messages: list[dict]) -> TutorView:
        return TutorView(
            enabled=self.settings.ai_tutor_enabled,
            status=conversation.status if conversation else IDLE,
            messages=messages,
            proposal=conversation.pending_proposal if conversation else None,
        )

    async def view(self, deck_id: int, user: User) -> TutorView:
        await self._owned_deck(deck_id, user)
        conversation = await self.conversations.for_deck(deck_id)
        if conversation is None:
            return self._view(None, [])
        await self.session.commit()  # the checkpointer may wait for a connection of its own
        async with open_checkpointer(self.settings.database_url) as checkpointer:
            messages = await read_messages(checkpointer, conversation.thread_id)
        return self._view(conversation, messages)

    async def _check_budgets(self, user_id: int) -> None:
        settings = self.settings
        site, own = await self.budget.feature_calls(TUTOR, user_id)
        if site + TURN_MAX_CALLS > settings.ai_tutor_daily_limit:
            raise BudgetExceeded(SITE_LIMIT)
        if own + TURN_MAX_CALLS > settings.ai_tutor_user_daily_limit:
            raise BudgetExceeded(USER_LIMIT)
        if not await self.budget.within_model_limits(TURN_COST):
            raise BudgetExceeded(SITE_LIMIT)

    def _similar_card_finder(
        self, deck_id: int, usage: RunUsage
    ) -> Callable[[str], Awaitable[list[dict]]]:
        """A search limited to this deck, so the model can't reach another one."""
        try:
            embeddings = load_embeddings(self.settings, usage, learner_waiting=True)
        except AIUnavailable:
            return no_similar_cards
        model = model_name(Role.EMBEDDER, self.settings)
        session_in_use = asyncio.Lock()  # a model can ask for several searches at once

        async def find_similar(query: str) -> list[dict]:
            try:
                with ai_errors():
                    vector = await embeddings.aembed_query(query)
            except (AIRateLimited, AIUnavailable):
                return []  # the tool still has word matches
            async with session_in_use:
                found = [
                    {"front": card.front, "back": card.back, "lapses": card.lapses}
                    for card in await self.cards.nearest_in_deck(
                        deck_id, vector, model, MAX_TOOL_CARDS
                    )
                ]
                await self.session.commit()  # frees the connection while the model runs
            return found

        return find_similar

    async def send_message(self, deck_id: int, user: User, text: str) -> TutorView:
        """Run one turn of the chat, and save what it produced."""
        deck = await self._owned_deck(deck_id, user)
        if not self.settings.ai_tutor_enabled:
            raise NotAvailable(TURNED_OFF)
        await self._check_budgets(user.id)
        usage = RunUsage()
        try:
            writer = load_chat_model(Role.WRITER, self.settings, usage, learner_waiting=True)
            judge = load_chat_model(Role.JUDGE, self.settings, usage, learner_waiting=True)
        except AIUnavailable as error:
            raise NotAvailable(error.message) from None

        conversation = await self.conversations.get_or_create(deck_id, user.id)
        if conversation.status == AWAITING_DECISION:
            await self.session.commit()
            raise Conflict("Add or decline the suggested cards first.")
        if conversation.message_count >= MAX_MESSAGES:
            await self.session.commit()
            raise InvalidRequest("This chat is full. Reset it to keep going.", field="text")
        if not await self.conversations.claim(conversation, utcnow() - STALE_AFTER):
            await self.session.commit()
            raise Conflict(STILL_REPLYING)

        # Only this deck's cards are loaded, which is all the agent's tools can ever read.
        cards = [
            {"front": card.front, "back": card.back, "lapses": card.lapses}
            for card in await self.cards.texts_in_deck(deck_id)
        ]
        context = TutorContext(
            writer=writer,
            judge=judge,
            deck_name=deck.name,
            cards=cards,
            find_similar=self._similar_card_finder(deck_id, usage),
        )
        await self.session.commit()  # holds the claim for other requests, and frees the connection

        outcome = None
        try:
            async with (
                labelled_trace(
                    "tutor_turn",
                    user.id,
                    deck_id=deck_id,
                    thread_id=conversation.thread_id,
                    prompt_version=TUTOR_PROMPT_VERSION,
                ),
                open_checkpointer(self.settings.database_url) as checkpointer,
            ):
                outcome = await run_turn(context, checkpointer, conversation.thread_id, text)
        except Exception as error:
            # The type only, since the text can contain learner content.
            logger.warning("tutor outcome=turn_error type=%s", type(error).__name__)

        # The learner may have deleted the deck while the model ran, which also deleted this row.
        deleted = await self.conversations.for_deck(deck_id) is None
        # Any calls made before a failure still spent quota.
        self.budget.record(
            TUTOR, user.id, None if deleted else deck_id, usage, TUTOR_PROMPT_VERSION
        )
        if deleted:
            await self.session.commit()
            await discard_threads(self.settings.database_url, [conversation.thread_id])
            raise NotFound(DECK_NOT_FOUND)
        if outcome is None:
            conversation.status = IDLE
            conversation.status_at = utcnow()
            await self.session.commit()
            raise NotAvailable(NO_REPLY)

        conversation.message_count = len(outcome.messages)
        conversation.status = AWAITING_DECISION if outcome.proposal else IDLE
        conversation.status_at = utcnow()
        conversation.pending_proposal = (
            {**outcome.proposal, "verification": outcome.verification}
            if outcome.proposal
            else None
        )
        await self.session.commit()
        return self._view(conversation, outcome.messages)

    async def decide(self, deck_id: int, user: User, proposal_id: str, accept: bool) -> TutorView:
        """Add or decline the cards waiting for a decision."""
        await self._owned_deck(deck_id, user)
        # The lock, the status and the id tie this approval to one proposal, and use it once.
        conversation = await self.conversations.for_deck(deck_id, lock=True)
        proposal = conversation.pending_proposal if conversation else None
        if (
            proposal is None
            or conversation.status != AWAITING_DECISION
            or proposal_id != proposal["id"]
        ):
            raise Conflict("Those suggested cards are no longer waiting for a decision.")

        added: list[Card] = []
        if accept:
            # Cards come from the server's copy, and the deck may have changed since.
            drafts = clean_cards(
                [CardDraft(**card) for card in proposal["cards"]],
                len(proposal["cards"]),
                normalized_fronts(await self.cards.fronts_in_deck(deck_id)),
            )
            added = await self.cards.add_many(
                [
                    Card(deck_id=deck_id, front=draft.front, back=draft.back, origin="ai")
                    for draft in drafts
                ]
            )
        if added:
            await self.jobs.add(
                Job(
                    user_id=user.id,
                    kind=EMBED_CARDS,
                    payload={"card_ids": [card.id for card in added]},
                )
            )
        conversation.pending_proposal = None
        conversation.status = IDLE
        conversation.status_at = utcnow()
        conversation.message_count += 1
        await self.session.commit()

        # The database is the record of what happened, so it commits first. A failure here only
        # leaves the closing message out of the chat, and the next message starts a new turn.
        closing = (
            f"Added {len(added)} {'card' if len(added) == 1 else 'cards'} to your deck."
            if accept
            else "Okay, I won't add those."
        )
        async with open_checkpointer(self.settings.database_url) as checkpointer:
            try:
                async with labelled_trace(
                    "tutor_decision", user.id, deck_id=deck_id, thread_id=conversation.thread_id
                ):
                    await resume_turn(checkpointer, conversation.thread_id, closing)
            except Exception as error:
                logger.warning("tutor outcome=resume_failed type=%s", type(error).__name__)
            messages = await read_messages(checkpointer, conversation.thread_id)
        return self._view(conversation, messages)

    async def reset(self, deck_id: int, user: User) -> None:
        """Delete the deck's chat and its saved history."""
        await self._owned_deck(deck_id, user)
        conversation = await self.conversations.for_deck(deck_id)
        if conversation is None:
            return
        if conversation.status == REPLYING:
            raise Conflict(STILL_REPLYING)
        thread_id = conversation.thread_id
        await self.conversations.delete(conversation)
        await self.session.commit()
        await discard_threads(self.settings.database_url, [thread_id])
