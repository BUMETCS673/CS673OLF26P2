"""Creating, reading, changing and deleting cards."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BudgetExceeded, NotFound
from app.models import Card, Job, User, utcnow
from app.models.job import EMBED_CARDS
from app.repositories.cards import CardRepository
from app.repositories.decks import DeckRepository
from app.repositories.generations import GenerationRepository
from app.repositories.jobs import JobRepository
from app.repositories.knowledge import NEAR_DUPLICATE_SIMILARITY, KnowledgeRepository
from app.repositories.users import UserRepository
from app.schemas.cards import CardCreate, CardUpdate
from app.services.budget import BUDGET_WINDOW
from app.services.decks import DECK_NOT_FOUND
from app.services.trust import revoke_if_reported

CARD_NOT_FOUND = "Card not found"
# A report hides shared chunks at once, so this limits how much one account can hide.
MAX_REPORTS_PER_DAY = 20


class CardService:
    def __init__(
        self,
        session: AsyncSession,
        decks: DeckRepository,
        cards: CardRepository,
        jobs: JobRepository,
        knowledge: KnowledgeRepository,
        generations: GenerationRepository,
        users: UserRepository,
    ):
        self.session = session
        self.decks = decks
        self.cards = cards
        self.jobs = jobs
        self.knowledge = knowledge
        self.generations = generations
        self.users = users

    async def _queue_embedding(self, card: Card, user: User) -> None:
        """Only for searching its own deck: a learner's own text never joins the knowledge base."""
        await self.jobs.add(
            Job(
                user_id=user.id,
                kind=EMBED_CARDS,
                payload={"card_ids": [card.id], "share": False},
            )
        )

    async def _require_deck(self, deck_id: int, user: User) -> None:
        if await self.decks.get_owned(deck_id, user.id) is None:
            raise NotFound(DECK_NOT_FOUND)

    async def _owned(self, card_id: int, user: User) -> Card:
        card = await self.cards.get_owned(card_id, user.id)
        if card is None:
            raise NotFound(CARD_NOT_FOUND)
        return card

    async def list_cards(self, deck_id: int, user: User) -> list[Card]:
        await self._require_deck(deck_id, user)
        return await self.cards.list_for_deck(deck_id)

    async def create(self, deck_id: int, user: User, body: CardCreate) -> Card:
        await self._require_deck(deck_id, user)
        card = await self.cards.add(Card(deck_id=deck_id, front=body.front, back=body.back))
        await self._queue_embedding(card, user)
        await self.session.commit()
        return card

    async def update(self, card_id: int, user: User, body: CardUpdate) -> Card:
        card = await self._owned(card_id, user)
        changes = body.model_dump(exclude_unset=True)
        text_changed = (
            changes.get("front", card.front) != card.front
            or changes.get("back", card.back) != card.back
        )
        for field, value in changes.items():
            setattr(card, field, value)
        if text_changed:
            await self._queue_embedding(card, user)
        await self.session.commit()
        return card

    async def report(self, card_id: int, user: User) -> None:
        """Hide what the card came from, right away, since hiding only ever narrows shared search.

        The card stays in the deck, and a learner keeps access to their own files.
        """
        card = await self._owned(card_id, user)
        reports = await self.cards.count_reports_since(user.id, utcnow() - BUDGET_WINDOW)
        if reports >= MAX_REPORTS_PER_DAY:
            raise BudgetExceeded("You've reached today's limit for reporting cards.")
        if not await self.cards.add_report(card.id, user.id):
            return  # already reported

        hidden = await self.knowledge.hide_card_copy(card.id)
        # A second learner's card has no copy of its own, since it confirmed the first learner's.
        if embedded := await self.cards.embedding_of(card.id):
            match = await self.knowledge.closest_card(*embedded)
            if match is not None and match.similarity >= NEAR_DUPLICATE_SIMILARITY:
                hidden += await self.knowledge.hide_chunks([match.chunk_id])
        if card.generation_id is not None:
            generation = await self.generations.get_owned(card.generation_id, user.id)
            if generation is not None:
                hidden += await self.knowledge.hide_chunks(generation.source_chunk_ids)

        trusted = user.trusted_at is not None
        targets = await self.cards.add_chunk_reports(user.id, hidden, trusted)
        # Only a trusted report can be the one that takes an account's trust away.
        if trusted:
            now = utcnow()
            for target in targets:
                await revoke_if_reported(target, now, self.users, self.knowledge)
        await self.session.commit()

    async def delete(self, card_id: int, user: User) -> None:
        card = await self._owned(card_id, user)
        await self.cards.delete(card.id)
        await self.session.commit()
