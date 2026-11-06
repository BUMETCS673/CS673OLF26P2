"""The deck tutor: budgets, one conversation per deck, running turns, and applying proposals.

A turn runs inside the request, since it only waits on the network and the page shows the reply
when it returns. No database transaction stays open while the model runs.
"""

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import timedelta

from langchain_core.stores import ByteStore
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.cards.checks import clean_cards, normalized_fronts
from app.ai.cards.existing import existing_card_finder
from app.ai.checkpoints import discard_threads, open_checkpointer
from app.ai.knowledge.indexing import with_query_cache
from app.ai.models import (
    AIRateLimited,
    AIUnavailable,
    ChatModel,
    Role,
    RunModels,
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
    TurnOutcome,
    read_messages,
    resume_turn,
    run_turn,
)
from app.ai.tutor.prompts import TUTOR_PROMPT_VERSION
from app.ai.tutor.tools import MAX_TOOL_CARDS
from app.ai.usage import RunUsage
from app.core.errors import BudgetExceeded, Conflict, InvalidRequest, NotAvailable, NotFound
from app.core.settings import Settings
from app.models import Card, Deck, TutorConversation, User, utcnow
from app.models.tutor import AWAITING_DECISION, IDLE, REPLYING
from app.repositories.cards import CardRepository
from app.repositories.jobs import JobRepository
from app.repositories.tutor import TutorRepository
from app.schemas.tutor import TutorView
from app.services.budget import TUTOR, USER, BudgetService
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
        cards: CardRepository,
        jobs: JobRepository,
        budget: BudgetService,
        settings: Settings,
        cache: ByteStore | None = None,  # for embeddings
    ):
        self.session = session  # one request's transaction so nothing saves until commit
        self.conversations = conversations
        self.cards = cards
        self.jobs = jobs
        self.budget = budget
        self.settings = settings
        self.cache = cache  # Redis cache so repeated search queries skip the embedder
        # an AsyncSession can't run two queries at once and the agent may call tools in parallel
        self._session_in_use = asyncio.Lock()

    def _view(self, conversation: TutorConversation | None, messages: list[dict]) -> TutorView:
        return TutorView(  # the one shape every tutor route returns
            enabled=self.settings.ai_tutor_enabled,  # the page hides the chat when off
            status=conversation.status if conversation else IDLE,
            messages=messages,
            proposal=conversation.pending_proposal if conversation else None,  # cards to decide
        )

    async def view(self, deck: Deck) -> TutorView:
        # Step 1: a deck with no chat yet shows an empty one
        conversation = await self.conversations.for_deck(deck.id)
        if conversation is None:
            return self._view(None, [])  # no checkpointer connection needed
        # Step 2: read the messages from the chat's saved LangGraph run
        await self.session.commit()  # the checkpointer may wait for a connection of its own
        async with open_checkpointer(self.settings.database_url) as checkpointer:
            messages = await read_messages(checkpointer, conversation.thread_id)  # from state
        return self._view(conversation, messages)  # 200 to the client

    async def _check_budgets(self, user_id: int) -> RunModels:
        """The models this turn uses, if every budget has room."""
        # Step 1: check the site's and the learner's tutor limits and pick the models
        reached, models = await self.budget.limit_reached(
            TUTOR,
            user_id,
            TURN_COST,  # a turn's worst case of 3 helper calls, 1 judge and 2 embeddings
            user_limit=self.settings.ai_tutor_user_daily_limit,
            site_limit=self.settings.ai_tutor_daily_limit,
            judged=Role.HELPER,  # the judge checks the helper's proposed cards
        )
        # Step 2: refuse with the limit that was reached
        if reached:
            logger.info("tutor refused", extra={"user_id": user_id, "limit": reached})
            raise BudgetExceeded(USER_LIMIT if reached == USER else SITE_LIMIT)  # 429
        return models  # the turn uses exactly these so the check and the run agree

    def _similar_card_finder(
        self, deck_id: int, usage: RunUsage
    ) -> Callable[[str], Awaitable[list[dict]]]:
        """A search limited to this deck, so the model can't reach another one."""
        # Step 1: load the embedder because the search finds nothing without one
        try:
            embeddings = load_embeddings(self.settings, usage, learner_waiting=True)
        except AIUnavailable:  # with no API key the chat still works without vector search
            logger.info("tutor search off", extra={"deck_id": deck_id, "reason": "no_embedder"})
            return no_similar_cards
        # Step 2: cache query vectors so a repeated question doesn't call the model again
        model = model_name(Role.EMBEDDER, self.settings)  # the cache key includes the model
        if self.cache is not None:
            embeddings = with_query_cache(embeddings, self.cache, model)

        async def find_similar(query: str) -> list[dict]:  # a closure with deck_id fixed here
            # Step 1: embed the query and fall back to word matches if that fails
            try:
                with ai_errors():  # vendor errors become ours
                    vector = await embeddings.aembed_query(query)
            except (AIRateLimited, AIUnavailable):
                logger.info("tutor search skipped", extra={"deck_id": deck_id})
                return []  # degrade quietly so one failed search doesn't end the turn
            # Step 2: find this deck's nearest cards
            async with self._cards_in_use() as cards:  # one query on the session at a time
                return [  # only what the model needs never ids or other learners' data
                    {"front": card.front, "back": card.back, "lapses": card.lapses}
                    # pgvector nearest neighbours filtered to this deck and embedding model
                    for card in await cards.nearest_in_deck(deck_id, vector, model, MAX_TOOL_CARDS)
                ]

        return find_similar

    @asynccontextmanager
    async def _cards_in_use(self) -> AsyncIterator[CardRepository]:
        """One search at a time, since a model can ask for several at once."""
        async with self._session_in_use:  # parallel tool calls queue here
            yield self.cards
            await self.session.commit()  # frees the connection while the model runs

    def _load_models(self, models: RunModels, usage: RunUsage) -> tuple[ChatModel, ChatModel]:
        """The writer and the judge for this turn."""
        try:
            writer = load_chat_model(  # the agent that chats and proposes cards
                # learner_waiting waits at most 12 s on the rate limiter then falls back
                Role.HELPER, self.settings, usage, learner_waiting=True, models=models
            )
            judge = load_chat_model(  # a stronger model that checks proposed cards
                Role.JUDGE, self.settings, usage, learner_waiting=True, models=models
            )
        except AIUnavailable as error:  # e.g no API key
            raise NotAvailable(error.message) from None  # 503
        return writer, judge

    async def _claim(self, deck_id: int, user_id: int) -> TutorConversation:
        """Claims the deck's chat so a second message can't run a turn at the same time."""
        # INSERT ... ON CONFLICT DO NOTHING keeps one chat per deck even with two first messages
        conversation = await self.conversations.get_or_create(deck_id, user_id)
        if conversation.status == AWAITING_DECISION:
            await self.session.commit()  # keeps a chat row that was just created
            logger.info("tutor refused", extra={"deck_id": deck_id, "reason": "awaiting_decision"})
            raise Conflict("Add or decline the suggested cards first.")  # 409
        if conversation.message_count >= MAX_MESSAGES:  # 100 bounds the prompt and its cost
            await self.session.commit()
            logger.info("tutor refused", extra={"deck_id": deck_id, "reason": "chat_full"})
            raise InvalidRequest("This chat is full. Reset it to keep going.", field="text")  # 422
        # a conditional UPDATE on idle or stale chats so only one request wins the claim
        if not await self.conversations.claim(conversation, utcnow() - STALE_AFTER):
            await self.session.commit()
            logger.info("tutor refused", extra={"deck_id": deck_id, "reason": "still_replying"})
            raise Conflict(STILL_REPLYING)  # 409
        return conversation

    async def _build_context(
        self, deck: Deck, writer: ChatModel, judge: ChatModel, usage: RunUsage
    ) -> TutorContext:
        """Loads only this deck's cards because the agent's tools may read nothing else."""
        deck_id = deck.id
        cards = [
            # lapses show the weak spots
            {"front": card.front, "back": card.back, "lapses": card.lapses}
            for card in await self.cards.texts_in_deck(deck_id)  # text columns only no vectors
        ]
        context = TutorContext(  # everything the graph and its tools may touch
            writer=writer,
            judge=judge,
            deck_name=deck.name,
            cards=cards,
            find_similar=self._similar_card_finder(deck_id, usage),  # vector search tool
            find_existing=existing_card_finder(  # duplicate check for proposed cards
                deck_id,
                self._cards_in_use,
                self.settings,
                usage,
                cache=self.cache,
                learner_waiting=True,
            ),
        )
        await self.session.commit()  # holds the claim for other requests and frees the connection
        logger.info("tutor context built", extra={"deck_id": deck_id, "cards": len(cards)})
        return context

    async def _run(
        self, context: TutorContext, conversation: TutorConversation, user_id: int, text: str
    ) -> TurnOutcome | None:
        """The turn's outcome or None if it failed."""
        try:
            # tags the LangSmith trace with deck, thread, prompt version and opens the chat history
            async with (
                labelled_trace(
                    "tutor_turn",
                    user_id,
                    deck_id=conversation.deck_id,
                    thread_id=conversation.thread_id,
                    prompt_version=TUTOR_PROMPT_VERSION,
                ),
                open_checkpointer(self.settings.database_url) as checkpointer,
            ):
                # the LangGraph run with agent tools then the judge if cards were proposed
                return await run_turn(context, checkpointer, conversation.thread_id, text)
        except Exception as error:  # caught broadly since the chat must be freed below either way
            # The type only, since the text can contain learner content.
            logger.warning("tutor outcome=turn_error type=%s", type(error).__name__)
            return None

    async def _save_turn(self, conversation: TutorConversation, outcome: TurnOutcome) -> TutorView:
        """Proposed cards wait in the chat for the learner's decision."""
        conversation.message_count = len(outcome.messages)  # counted for MAX_MESSAGES
        # proposed cards mean the graph paused at interrupt() waiting for decide()
        conversation.status = AWAITING_DECISION if outcome.proposal else IDLE
        conversation.status_at = utcnow()
        conversation.pending_proposal = (  # the server's copy so decide() never trusts input
            {**outcome.proposal, "verification": outcome.verification}  # with the judge's verdict
            if outcome.proposal
            else None
        )
        await self.session.commit()
        logger.info(
            "tutor turn done",
            extra={
                "deck_id": conversation.deck_id,
                "messages": len(outcome.messages),
                "proposed_cards": len(outcome.proposal["cards"]) if outcome.proposal else 0,
            },
        )
        return self._view(conversation, outcome.messages)  # 200 with the chat and the new reply

    async def send_message(self, deck: Deck, user: User, text: str) -> TutorView:
        """Run one turn of the chat, and save what it produced."""
        # Step 1: refuse if the tutor is off or over its limits then load its two models
        deck_id = deck.id
        logger.info("tutor turn started", extra={"user_id": user.id, "deck_id": deck_id})
        if not self.settings.ai_tutor_enabled:  # a kill switch in the environment
            raise NotAvailable(TURNED_OFF)  # 503 to the client
        models = await self._check_budgets(user.id)
        usage = RunUsage()  # callbacks count each call's model and tokens into this
        writer, judge = self._load_models(models, usage)

        # Step 2: refuse while cards wait for a decision or the chat is full then claim the
        # chat so a second message can't run a turn at the same time
        conversation = await self._claim(deck_id, user.id)

        # Step 3: build the turn's context from this deck's cards alone since the agent's tools
        # can read nothing else
        context = await self._build_context(deck, writer, judge, usage)

        # Step 4: run the turn and log any failure by type for the steps below to handle
        outcome = await self._run(context, conversation, user.id, text)

        # Step 5: save what the calls spent even before a failure and check whether the learner
        # deleted the deck while the model ran because that also deleted this row
        deleted = await self.conversations.for_deck(deck_id) is None
        self.budget.record(
            # None for a deleted deck since the usage row can't point at it
            TUTOR, user.id, None if deleted else deck_id, usage, TUTOR_PROMPT_VERSION
        )

        # Step 6: drop the run for a deleted deck or free the chat for another try after a failure
        if deleted:
            await self.session.commit()  # the usage row still saves
            await discard_threads(self.settings.database_url, [conversation.thread_id])
            logger.info("tutor turn dropped", extra={"deck_id": deck_id, "reason": "deck_deleted"})
            raise NotFound(DECK_NOT_FOUND)  # 404 to the client
        if outcome is None:  # the turn failed
            conversation.status = IDLE  # releases the claim so the learner can try again
            conversation.status_at = utcnow()
            await self.session.commit()
            logger.info("tutor turn failed", extra={"deck_id": deck_id})
            raise NotAvailable(NO_REPLY)  # 503

        # Step 7: save the turn with any proposed cards waiting for the learner's decision
        return await self._save_turn(conversation, outcome)

    async def decide(self, deck: Deck, user: User, proposal_id: str, accept: bool) -> TutorView:
        """Add or decline the cards waiting for a decision."""
        deck_id = deck.id
        # Step 1: lock the chat and check that the proposal still waits with the lock, status and id
        # tying this approval to one proposal used once
        conversation = await self.conversations.for_deck(deck_id, lock=True)  # FOR UPDATE
        proposal = conversation.pending_proposal if conversation else None
        if (
            proposal is None
            or conversation.status != AWAITING_DECISION
            or proposal_id != proposal["id"]  # a stale page can't approve a newer proposal
        ):
            raise Conflict("Those suggested cards are no longer waiting for a decision.")  # 409

        # Step 2: on accept add the cards skipping any the deck has gained since Cards come
        # from the server's copy never the request
        added: list[Card] = []
        if accept:
            drafts = clean_cards(  # drops empty cards, repeats and fronts that give away the back
                [CardDraft(**card) for card in proposal["cards"]],
                len(proposal["cards"]),
                # compared ignoring case, spacing and end punctuation built once per deck
                normalized_fronts(await self.cards.fronts_in_deck(deck_id)),
            )
            added = await self.cards.add_many(  # one multi-row INSERT
                [
                    Card(deck_id=deck_id, front=draft.front, back=draft.back, origin="ai")
                    for draft in drafts
                ]
            )
        # Step 3: queue the new cards' embedding, clear the proposal and free the chat in one
        # commit
        if added:
            await self.jobs.queue_card_embedding(user.id, [card.id for card in added])  # outbox
        conversation.pending_proposal = None  # used once
        conversation.status = IDLE  # the chat takes messages again
        conversation.status_at = utcnow()
        conversation.message_count += 1  # the closing message added below
        await self.session.commit()
        logger.info(
            "tutor proposal decided",
            extra={
                "deck_id": deck_id,
                "accepted": accept,
                "proposed": len(proposal["cards"]),
                "added": len(added),
            },
        )

        # Step 4: add the closing message to the chat's run only after the database has recorded
        # the outcome because a failure here then just leaves that message out and the next
        # message starts a new turn
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
                    # Command(resume=...) continues the paused run which writes the closing line
                    await resume_turn(checkpointer, conversation.thread_id, closing)
            except Exception as error:  # the cards are already saved so only log it
                logger.warning("tutor outcome=resume_failed type=%s", type(error).__name__)
            messages = await read_messages(checkpointer, conversation.thread_id)  # same connection
        return self._view(conversation, messages)  # 200 with the chat after the decision

    async def reset(self, deck: Deck) -> None:
        """Delete the deck's chat and its saved history."""
        # Step 1: nothing to reset without a chat and not while it's replying
        conversation = await self.conversations.for_deck(deck.id)
        if conversation is None:
            return  # 204 either way since resetting an empty chat isn't an error
        if conversation.status == REPLYING:  # a running turn would write into a deleted thread
            raise Conflict(STILL_REPLYING)  # 409
        # Step 2: delete the chat's row then its saved LangGraph run
        thread_id = conversation.thread_id  # kept because the row is gone after delete
        await self.conversations.delete(conversation)
        await self.session.commit()
        await discard_threads(self.settings.database_url, [thread_id])  # best effort
        logger.info("tutor chat reset", extra={"deck_id": deck.id})
