"""Creating, reading, changing and deleting decks."""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.checkpoints import discard_threads
from app.core.settings import Settings
from app.models import Deck, User, utcnow
from app.repositories.cards import CardRepository
from app.repositories.decks import DeckRepository
from app.schemas.decks import DeckCreate, DeckRead, DeckUpdate, DueCounts

logger = logging.getLogger(__name__)

DECK_NOT_FOUND = "Deck not found"


class DeckService:
    def __init__(
        self,
        session: AsyncSession,
        decks: DeckRepository,
        cards: CardRepository,
        settings: Settings,
    ):
        self.session = session  # one request's transaction so nothing saves until commit
        self.decks = decks
        self.cards = cards
        self.settings = settings

    async def _read(self, deck: Deck) -> DeckRead:
        return (await self._read_many([deck]))[0]  # one deck as a list of one uses the same query

    async def _read_many(self, decks: list[Deck]) -> list[DeckRead]:
        # Step 1: count every deck's cards and those due now in one grouped query One query
        # per deck would grow with the deck list
        counts = await self.cards.deck_counts([deck.id for deck in decks], utcnow())
        # Step 2: pair each deck with its counts
        return [
            DeckRead.build(deck, counts[deck.id].cards, DueCounts(**counts[deck.id].due))
            for deck in decks  # counts has every id zeros included so no KeyError
        ]

    async def list_decks(self, user: User) -> list[DeckRead]:
        # one query for the decks and one for their counts however many decks there are
        return await self._read_many(await self.decks.list_for_user(user.id))

    async def get(self, deck: Deck) -> DeckRead:
        return await self._read(deck)  # ownership was already checked by OwnedDeck

    async def create(self, user: User, body: DeckCreate) -> DeckRead:
        # Step 1: save the deck under its owner
        deck = await self.decks.add(
            Deck(user_id=user.id, name=body.name, description=body.description)
        )  # flushed so the deck has its id
        await self.session.commit()
        logger.info("deck created", extra={"user_id": user.id, "deck_id": deck.id})
        # Step 2: read it back with its (empty) card counts
        return await self._read(deck)  # 201 to the client from the router

    async def update(self, deck: Deck, body: DeckUpdate) -> DeckRead:
        # Step 1: change only the fields the request sent
        changes = body.model_dump(exclude_unset=True)  # a PATCH so unsent fields stay as they are
        for field, value in changes.items():
            setattr(deck, field, value)  # tracked by SQLAlchemy written as one UPDATE on commit
        await self.session.commit()
        logger.info("deck updated", extra={"deck_id": deck.id, "fields": ",".join(changes)})
        # Step 2: read it back with its card counts
        return await self._read(deck)

    async def delete(self, deck: Deck) -> None:
        # Step 1: note the deck's saved LangGraph runs (tutor chat, problem card reviews) first
        thread_ids = await self.decks.graph_thread_ids(deck.id)  # read before the rows go
        # Step 2: delete the deck Its cards, batches, reviews and chat go with it by cascade
        await self.decks.delete(deck.id)  # one DELETE and ON DELETE CASCADE does the rest
        await self.session.commit()  # the deck is gone even if step 3 fails
        # Step 3: drop those runs' checkpoints which the cascade can't reach
        if thread_ids:  # skip the extra connection when there's nothing to drop
            await discard_threads(self.settings.database_url, thread_ids)
        logger.info("deck deleted", extra={"deck_id": deck.id, "threads": len(thread_ids)})
