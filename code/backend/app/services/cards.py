"""Creating, reading, changing and deleting cards."""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BudgetExceeded, found
from app.models import Card, Deck, User, utcnow
from app.repositories.card_reports import CardReportRepository
from app.repositories.cards import CardRepository
from app.repositories.generations import GenerationRepository
from app.repositories.jobs import JobRepository
from app.repositories.knowledge import KnowledgeRepository
from app.repositories.users import UserRepository
from app.schemas.cards import CardCreate, CardUpdate
from app.services.budget import BUDGET_WINDOW
from app.services.trust import revoke_if_reported

logger = logging.getLogger(__name__)

CARD_NOT_FOUND = "Card not found"
# A report hides shared chunks at once, so this limits how much one account can hide.
MAX_REPORTS_PER_DAY = 20


class CardService:
    def __init__(
        self,
        session: AsyncSession,
        cards: CardRepository,
        reports: CardReportRepository,
        jobs: JobRepository,
        knowledge: KnowledgeRepository,
        generations: GenerationRepository,
        users: UserRepository,
    ):
        self.session = session  # one request's transaction so nothing saves until commit
        self.cards = cards
        self.reports = reports
        self.jobs = jobs
        self.knowledge = knowledge
        self.generations = generations
        self.users = users

    async def _queue_embedding(self, card: Card, user: User) -> None:
        """Only for searching its own deck: a learner's own text never joins the knowledge base."""
        # an outbox row in this transaction so the worker can't miss it after commit
        await self.jobs.queue_card_embedding(user.id, [card.id], share=False)

    async def _owned(self, card_id: int, user: User) -> Card:
        # joins the deck to check the owner
        return found(await self.cards.get_owned(card_id, user.id), CARD_NOT_FOUND)

    async def list_cards(self, deck: Deck) -> list[Card]:
        return await self.cards.list_for_deck(deck.id)  # ownership already checked by OwnedDeck

    async def create(self, deck: Deck, user: User, body: CardCreate) -> Card:
        # Step 1: save the card
        card = await self.cards.add(Card(deck_id=deck.id, front=body.front, back=body.back))
        # Step 2: queue its embedding in the same commit so the job can't be lost
        await self._queue_embedding(card, user)
        await self.session.commit()  # card and its job together or neither
        logger.info("card created", extra={"deck_id": deck.id, "card_id": card.id})
        return card  # 201 to the client from the router

    async def create_many(self, deck: Deck, user: User, bodies: list[CardCreate]) -> list[Card]:
        """Several cards in one commit with one embedding job for all of them."""
        # Step 1: save every card in one multi-row INSERT
        cards = await self.cards.add_many(
            [Card(deck_id=deck.id, front=body.front, back=body.back) for body in bodies]
        )
        # Step 2: queue one embedding job for them all in the same commit
        await self.jobs.queue_card_embedding(user.id, [card.id for card in cards], share=False)
        await self.session.commit()  # all the cards and their job together or none of them
        logger.info("cards created", extra={"deck_id": deck.id, "cards": len(cards)})
        return cards

    async def update(self, card_id: int, user: User, body: CardUpdate) -> Card:
        # Step 1: load the learner's card
        card = await self._owned(card_id, user)

        # Step 2: note whether its text changes before applying the fields the request sent
        changes = body.model_dump(exclude_unset=True)  # a PATCH so unsent fields stay as they are
        text_changed = (
            changes.get("front", card.front) != card.front  # an unsent field counts as unchanged
            or changes.get("back", card.back) != card.back
        )
        for field, value in changes.items():
            setattr(card, field, value)  # tracked by SQLAlchemy written as one UPDATE on commit

        # Step 3: new text needs a new embedding so search finds the card by what it says now
        if text_changed:  # a no-op edit spends no embedding call
            await self._queue_embedding(card, user)
        await self.session.commit()
        logger.info("card updated", extra={"card_id": card.id, "text_changed": text_changed})
        return card  # 200 with the saved card

    async def report(self, card_id: int, user: User) -> None:
        """Hide what the card came from, right away, since hiding only ever narrows shared search.

        The card stays in the deck, and a learner keeps access to their own files.
        """
        # Step 1: load the learner's card and refuse once they've used today's reports
        card = await self._owned(card_id, user)
        # a rolling 24 hours instead of a calendar day so no burst at midnight
        reports = await self.reports.count_reports_since(user.id, utcnow() - BUDGET_WINDOW)
        if reports >= MAX_REPORTS_PER_DAY:  # caps how much shared content one account can hide
            logger.info("report refused", extra={"card_id": card.id, "reason": "daily_limit"})
            raise BudgetExceeded("You've reached today's limit for reporting cards.")  # 429

        # Step 2: record the report unless the learner already reported this card
        # INSERT ... ON CONFLICT DO NOTHING avoids a race between checking and inserting
        if not await self.reports.add_report(card.id, user.id):
            logger.info("report skipped", extra={"card_id": card.id, "reason": "already_reported"})
            return  # 204 either way since reporting twice isn't an error

        # Step 3: hide every shared chunk the card came from which is its own copy, the chunk
        # it confirmed and the material its AI batch was written from
        sources: list[str] = []
        # A second learner's card has no copy of its own, since it confirmed the first learner's.
        if card.confirmed_chunk_id is not None:
            sources.append(str(card.confirmed_chunk_id))
        if card.generation_id is not None:  # an AI card also hides the material it was written from
            generation = await self.generations.get_owned(card.generation_id, user.id)
            if generation is not None:  # None if the batch was deleted with its deck
                sources += generation.source_chunk_ids
        # one UPDATE for the card's copy in shared search and every chunk it came from
        hidden = await self.knowledge.hide_card_sources(card.id, sources)

        # Step 4: count the report against each hidden chunk's author
        trusted = user.trusted_at is not None  # a trusted reporter's reports weigh on trust
        # one insert for every hidden chunk returning the authors it counted against
        targets = await self.reports.add_chunk_reports(user.id, hidden, trusted)

        # Step 5: let a trusted report take trust away from authors with enough reports
        if trusted:  # untrusted accounts can't knock others' trust down
            now = utcnow()
            for target in targets:  # few authors per card so one check each is cheap
                await revoke_if_reported(target, now, self.users, self.knowledge)
        await self.session.commit()  # report, hiding and trust changes saved together
        logger.info(
            "card reported",
            extra={
                "card_id": card.id,
                "hidden_chunks": len(hidden),
                "authors": len(targets),
            },
        )

    async def delete(self, card_id: int, user: User) -> None:
        # Step 1: load the learner's card then delete it
        card = await self._owned(card_id, user)  # 404 for someone else's card
        # reports go by cascade and a shared copy stays unlinked by SET NULL
        await self.cards.delete(card.id)
        await self.session.commit()
        logger.info("card deleted", extra={"card_id": card.id})
