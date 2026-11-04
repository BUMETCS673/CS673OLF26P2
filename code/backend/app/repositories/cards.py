"""Queries for cards. A card is yours only if its deck is yours."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import ColumnElement, Row, and_, delete, func, select, true, union, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models import Card, CardReport, ChunkReport, Deck, utcnow
from app.repositories.knowledge import HiddenChunk
from app.scheduler import LEARN_AHEAD, NEW_CARDS_PER_SESSION, REVIEWS_PER_SESSION, CardState


def due_conditions(now: datetime) -> dict[str, ColumnElement[bool]]:
    """One condition per list the study session serves. The counts use these too, so they agree."""
    return {
        "learning": and_(
            Card.state.in_((CardState.LEARNING.value, CardState.RELEARNING.value)),
            Card.due_at <= now + LEARN_AHEAD,
        ),
        "review": and_(Card.state == CardState.REVIEW.value, Card.due_at <= now),
        "new": Card.state == CardState.NEW.value,
    }


@dataclass(frozen=True)
class DeckCounts:
    cards: int
    due: dict[str, int]  # capped at what one study session serves


class CardRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def save_embeddings(self, vectors: dict[int, list[float]], model: str) -> None:
        """One bulk UPDATE by primary key, sent as a single batch however many cards there are."""
        if vectors:
            await self.session.execute(
                update(Card),
                [
                    {"id": card_id, "embedding": vector, "embedding_model": model}
                    for card_id, vector in vectors.items()
                ],
            )

    async def save_confirmed_chunks(self, chunk_ids: dict[int, str]) -> None:
        """Saves each card's confirmed copy in one bulk UPDATE."""
        if chunk_ids:
            await self.session.execute(
                update(Card),
                [
                    {"id": card_id, "confirmed_chunk_id": uuid.UUID(chunk_id)}
                    for card_id, chunk_id in chunk_ids.items()
                ],
            )

    async def add_report(self, card_id: int, user_id: int) -> bool:
        """Whether this is a new report. Repeating one changes nothing."""
        # RETURNING, since an ORM insert's rowcount isn't reliable: it can be -1.
        added = await self.session.scalar(
            insert(CardReport)
            .values(card_id=card_id, user_id=user_id)
            .on_conflict_do_nothing(index_elements=["user_id", "card_id"])
            .returning(CardReport.id)
        )
        return added is not None

    async def add_chunk_reports(
        self, reporter_id: int, hidden: Sequence[HiddenChunk], reporter_trusted: bool
    ) -> set[int]:
        """Who the hidden chunks are held against. The reporter's own chunks don't count."""
        rows = [
            {
                "reporter_id": reporter_id,
                "target_user_id": chunk.source_user_id,
                "chunk_id": chunk.chunk_id,
                "reporter_trusted": reporter_trusted,
                "created_at": utcnow(),
            }
            for chunk in hidden
            if chunk.source_user_id is not None and chunk.source_user_id != reporter_id
        ]
        if rows:
            await self.session.execute(
                insert(ChunkReport)
                .values(rows)
                .on_conflict_do_nothing(index_elements=["reporter_id", "chunk_id"])
            )
        return {row["target_user_id"] for row in rows}

    async def count_reports_since(self, user_id: int, since: datetime) -> int:
        return await self.session.scalar(
            select(func.count())
            .select_from(CardReport)
            .where(CardReport.user_id == user_id, CardReport.created_at >= since)
        )

    async def nearest_in_deck(
        self, deck_id: int, vector: list[float], model: str, limit: int
    ) -> list[Card]:
        """A deck is small enough to compare exactly, so this needs no vector index."""
        return list(
            await self.session.scalars(
                select(Card)
                .where(Card.deck_id == deck_id, Card.embedding_model == model)
                .order_by(Card.embedding.cosine_distance(vector))
                .limit(limit)
            )
        )

    async def likely_repeats(
        self,
        deck_id: int,
        vectors: Sequence[list[float]],
        model: str,
        per_vector: int,
        unembedded: int,
    ) -> list[Row]:
        """The cards closest to each vector, plus the newest without one, in one query."""
        in_deck = Card.deck_id == deck_id
        picks = [
            select(Card.id)
            .where(in_deck, Card.embedding_model == model)
            .order_by(Card.embedding.cosine_distance(vector))
            .limit(per_vector)
            for vector in vectors
        ]
        picks.append(
            select(Card.id)
            .where(in_deck, Card.embedding_model.is_distinct_from(model))
            .order_by(Card.id.desc())
            .limit(unembedded)
        )
        # Each pick is a subquery, since a UNION member can't have its own ORDER BY and LIMIT.
        ids = union(*(select(pick.subquery().c.id) for pick in picks))
        rows = await self.session.execute(
            select(Card.front, Card.back).where(Card.id.in_(ids)).order_by(Card.id.desc())
        )
        return list(rows)

    async def similar_in_deck(self, card_ids: Sequence[int], limit: int) -> dict[int, list[Row]]:
        """Each card's closest cards in its own deck by meaning, in one LATERAL query."""
        if not card_ids:
            return {}
        source = aliased(Card)
        distance = Card.embedding.cosine_distance(source.embedding)
        nearest = (
            select(Card.front, Card.back, distance.label("distance"))
            .where(
                Card.deck_id == source.deck_id,
                Card.id != source.id,
                Card.embedding_model == source.embedding_model,
            )
            .order_by(distance)
            .limit(limit)
            .lateral()
        )
        rows = await self.session.execute(
            select(source.id, nearest.c.front, nearest.c.back)
            .join(nearest, true())
            .where(source.id.in_(card_ids), source.embedding.is_not(None))
            .order_by(source.id, nearest.c.distance)
        )
        similar: dict[int, list[Row]] = {card_id: [] for card_id in card_ids}
        for row in rows:
            similar[row.id].append(row)
        return similar

    async def list_for_deck(self, deck_id: int) -> list[Card]:
        statement = select(Card).where(Card.deck_id == deck_id).order_by(Card.id)
        return list(await self.session.scalars(statement))

    async def texts_in_deck(self, deck_id: int) -> list[Row]:
        """Only what the AI features read, so a big deck doesn't load every scheduling column."""
        rows = await self.session.execute(
            select(Card.id, Card.front, Card.back, Card.lapses)
            .where(Card.deck_id == deck_id)
            .order_by(Card.id)
        )
        return list(rows)

    async def get_many(self, card_ids: list[int]) -> list[Card]:
        cards = await self.session.scalars(
            select(Card).where(Card.id.in_(card_ids)).order_by(Card.id)
        )
        return list(cards)

    async def problem_cards(self, deck_id: int, limit: int) -> list[Card]:
        """The deck's cards at or past their lapse limit, most lapses first."""
        cards = await self.session.scalars(
            select(Card)
            .where(Card.deck_id == deck_id, Card.lapses >= Card.problem_at_lapses)
            .order_by(Card.lapses.desc(), Card.id)
            .limit(limit)
        )
        return list(cards)

    async def newest_in_deck(self, deck_id: int, limit: int) -> list[Card]:
        cards = await self.session.scalars(
            select(Card).where(Card.deck_id == deck_id).order_by(Card.id.desc()).limit(limit)
        )
        return list(cards)

    async def fronts_in_deck(self, deck_id: int) -> list[str]:
        return list(await self.session.scalars(select(Card.front).where(Card.deck_id == deck_id)))

    async def get_owned(self, card_id: int, user_id: int, *, lock: bool = False) -> Card | None:
        """`lock` holds the row until the commit, so two requests can't change it at once."""
        statement = (
            select(Card)
            .join(Deck, Card.deck_id == Deck.id)
            .where(Card.id == card_id, Deck.user_id == user_id)
        )
        if lock:
            statement = statement.with_for_update(of=Card)
        return await self.session.scalar(statement)

    async def add(self, card: Card) -> Card:
        self.session.add(card)
        await self.session.flush()
        return card

    async def add_many(self, cards: list[Card]) -> list[Card]:
        """One flush, which SQLAlchemy sends as a multi-row INSERT ... RETURNING for the ids."""
        if cards:
            self.session.add_all(cards)
            await self.session.flush()
        return cards

    async def delete(self, card_id: int) -> None:
        await self.delete_many([card_id])

    async def delete_many(self, card_ids: list[int]) -> None:
        if card_ids:
            await self.session.execute(delete(Card).where(Card.id.in_(card_ids)))

    async def move_due_dates_earlier(self, user_id: int, by: timedelta) -> int:
        """In one statement, whatever the card count. Returns how many cards moved."""
        result = await self.session.execute(
            update(Card)
            .where(
                Card.deck_id.in_(select(Deck.id).where(Deck.user_id == user_id)),
                Card.due_at.is_not(None),
            )
            .values(due_at=Card.due_at - by)
        )
        return result.rowcount

    async def due_cards(self, deck_id: int, now: datetime) -> dict[str, list[Card]]:
        """What a study session serves: most overdue first, and new cards oldest first."""
        conditions = due_conditions(now)
        in_deck = select(Card).where(Card.deck_id == deck_id)
        learning = in_deck.where(conditions["learning"]).order_by(Card.due_at, Card.id)
        review = (
            in_deck.where(conditions["review"])
            .order_by(Card.due_at, Card.id)
            .limit(REVIEWS_PER_SESSION)
        )
        new = in_deck.where(conditions["new"]).order_by(Card.id).limit(NEW_CARDS_PER_SESSION)
        return {
            "learning": list(await self.session.scalars(learning)),
            "review": list(await self.session.scalars(review)),
            "new": list(await self.session.scalars(new)),
        }

    async def deck_counts(self, deck_ids: Sequence[int], now: datetime) -> dict[int, DeckCounts]:
        """Each deck's card count and due counts, in one grouped query however many decks."""
        conditions = due_conditions(now)
        # A deck with no cards has no row, so it keeps these zeros.
        counts = {deck_id: DeckCounts(0, dict.fromkeys(conditions, 0)) for deck_id in deck_ids}
        if not counts:
            return counts

        rows = await self.session.execute(
            select(
                Card.deck_id,
                func.count().label("cards"),
                *(
                    func.count().filter(condition).label(name)
                    for name, condition in conditions.items()
                ),
            )
            .where(Card.deck_id.in_(counts))
            .group_by(Card.deck_id)
        )
        for row in rows:
            counts[row.deck_id] = DeckCounts(
                row.cards,
                {
                    "learning": row.learning,
                    "review": min(row.review, REVIEWS_PER_SESSION),
                    "new": min(row.new, NEW_CARDS_PER_SESSION),
                },
            )
        return counts
