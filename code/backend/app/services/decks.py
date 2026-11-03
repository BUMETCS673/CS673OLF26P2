"""Creating, reading, changing and deleting decks."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.checkpoints import discard_threads
from app.core.errors import NotFound
from app.core.settings import Settings
from app.models import Deck, User, utcnow
from app.repositories.cards import CardRepository
from app.repositories.decks import DeckRepository
from app.schemas.decks import DeckCreate, DeckRead, DeckUpdate, DueCounts

DECK_NOT_FOUND = "Deck not found"


class DeckService:
    def __init__(
        self,
        session: AsyncSession,
        decks: DeckRepository,
        cards: CardRepository,
        settings: Settings,
    ):
        self.session = session
        self.decks = decks
        self.cards = cards
        self.settings = settings

    async def _owned(self, deck_id: int, user: User) -> Deck:
        deck = await self.decks.get_owned(deck_id, user.id)
        if deck is None:
            raise NotFound(DECK_NOT_FOUND)
        return deck

    async def _read(self, deck: Deck) -> DeckRead:
        return (await self._read_many([deck]))[0]

    async def _read_many(self, decks: list[Deck]) -> list[DeckRead]:
        counts = await self.cards.deck_counts([deck.id for deck in decks], utcnow())
        return [
            DeckRead.build(deck, counts[deck.id].cards, DueCounts(**counts[deck.id].due))
            for deck in decks
        ]

    async def list_decks(self, user: User) -> list[DeckRead]:
        return await self._read_many(await self.decks.list_for_user(user.id))

    async def get(self, deck_id: int, user: User) -> DeckRead:
        return await self._read(await self._owned(deck_id, user))

    async def create(self, user: User, body: DeckCreate) -> DeckRead:
        deck = await self.decks.add(
            Deck(user_id=user.id, name=body.name, description=body.description)
        )
        await self.session.commit()
        return await self._read(deck)

    async def update(self, deck_id: int, user: User, body: DeckUpdate) -> DeckRead:
        deck = await self._owned(deck_id, user)
        for field, value in body.model_dump(exclude_unset=True).items():
            setattr(deck, field, value)
        await self.session.commit()
        return await self._read(deck)

    async def delete(self, deck_id: int, user: User) -> None:
        deck = await self._owned(deck_id, user)
        thread_ids = await self.decks.graph_thread_ids(deck.id)
        await self.decks.delete(deck.id)
        await self.session.commit()
        if thread_ids:
            await discard_threads(self.settings.database_url, thread_ids)
