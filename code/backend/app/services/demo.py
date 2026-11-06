"""Demo data: one user with two decks, and moving their cards through time."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import found
from app.core.security import hash_password
from app.models import Card, Deck, User, normalize_email, utcnow
from app.repositories.cards import CardRepository
from app.repositories.decks import DeckRepository
from app.repositories.users import UserRepository
from app.scheduler import STARTING_EASE, CardSchedule, CardState

DEMO_EMAIL = "demo@cadence.local"
DEMO_PASSWORD = "demo1234"

SPANISH_CARDS = [
    ("la biblioteca", "the library"),
    ("el cuaderno", "the notebook"),
    ("aprender", "to learn"),
    ("la semana", "the week"),
]


def _card(
    front: str,
    back: str,
    now: datetime,
    state: CardState = CardState.NEW,
    due_in: timedelta | None = None,
    interval_days: int = 0,
    ease_factor: int = STARTING_EASE,
    step: int = 0,
    lapses: int = 0,
) -> Card:
    card = Card(front=front, back=back)
    card.schedule = CardSchedule(
        state=state,
        due_at=None if due_in is None else now + due_in,
        interval_days=interval_days,
        ease_factor=ease_factor,
        step=step,
        lapses=lapses,
    )
    return card


def _travel_cards(now: datetime) -> list[Card]:
    """A card at every stage: three reviews, three learning, three new, and two not due."""
    review, learning, relearning = CardState.REVIEW, CardState.LEARNING, CardState.RELEARNING
    return [
        _card("the airport", "el aeropuerto", now, review, -timedelta(days=4), interval_days=10),
        _card("the train station", "la estación de tren", now, review, -timedelta(days=1),
              interval_days=4),
        _card("the beach", "la playa", now, review, -timedelta(hours=1), interval_days=1),
        _card("the passport", "el pasaporte", now, relearning, -timedelta(minutes=5),
              interval_days=1, ease_factor=2300, lapses=1),
        _card("the suitcase", "la maleta", now, learning, -timedelta(minutes=2), step=1),
        _card("the ticket", "el boleto", now, learning, timedelta(minutes=8), step=1),
        _card("the hotel", "el hotel", now, review, timedelta(days=5), interval_days=12),
        _card("the map", "el mapa", now, review, timedelta(days=30), interval_days=40),
        _card("goodbye", "adiós", now),
        _card("the library", "la biblioteca", now),
        _card("the song", "la canción", now),
    ]


@dataclass(frozen=True)
class SeededDeck:
    id: int
    name: str
    card_count: int


class DemoService:
    def __init__(
        self,
        session: AsyncSession,
        users: UserRepository,
        decks: DeckRepository,
        cards: CardRepository,
    ):
        self.session = session
        self.users = users
        self.decks = decks
        self.cards = cards

    async def seed(self, *, reset: bool = False) -> list[SeededDeck] | None:
        """The new decks, or None if the demo user already exists and `reset` is off."""
        # Step 1: keep an existing demo user or delete it when resetting with the database's
        # cascade removing their decks
        existing = await self.users.get_by_email(DEMO_EMAIL)
        if existing is not None:
            if not reset:
                return None  # idempotent so running the seed twice changes nothing
            await self.users.delete(existing.id)  # ON DELETE CASCADE removes decks and cards

        # Step 2: add the demo user with one clock reading so every due time is relative to the
        # same moment
        now = utcnow()
        user = await self.users.add(  # flushed so the decks can point at its id
            User(
                email=DEMO_EMAIL,
                display_name="Demo User",
                # a real Argon2 hash so login works
                password_hash=await hash_password(DEMO_PASSWORD),
            )
        )
        # Step 3: add their two decks and cards then commit everything at once
        seeded = [
            await self._add_deck(
                user,
                "Spanish 101",
                "Core vocabulary",
                [_card(front, back, now) for front, back in SPANISH_CARDS],  # all new
            ),
            await self._add_deck(
                user,
                "Travel Spanish",
                "English → Spanish, with cards at every stage",
                _travel_cards(now),  # new, learning, review, due and not due for demos
            ),
        ]
        await self.session.commit()  # all or nothing so no half-seeded demo user
        return seeded  # the CLI prints each deck and its card count

    async def time_travel(self, days: int, email: str = DEMO_EMAIL) -> tuple[str, int]:
        """Move a user's due times `days` earlier. Returns their email and how many moved."""
        # Step 1: find the user by email
        # normalized like at sign-up so "Demo@Cadence.local" finds the same user
        user = found(
            await self.users.get_by_email(normalize_email(email)),
            f"No user with the email {email}.",  # the CLI shows this message
        )
        # Step 2: move all their cards' due times earlier in one update
        # one UPDATE that shifts due_at in SQL with no rows loaded into Python
        moved = await self.cards.move_due_dates_earlier(user.id, timedelta(days=days))
        await self.session.commit()
        return user.email, moved  # moved is the UPDATE's row count

    async def _add_deck(
        self, user: User, name: str, description: str, cards: list[Card]
    ) -> SeededDeck:
        # Step 1: add the deck then its cards under it
        deck = await self.decks.add(Deck(user_id=user.id, name=name, description=description))
        for card in cards:
            card.deck_id = deck.id  # the deck's id exists now that it's flushed
        await self.cards.add_many(cards)  # one multi-row INSERT for the deck's cards
        return SeededDeck(deck.id, deck.name, len(cards))
