"""Queries for reports of cards and the shared chunks they hide."""

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from app.models import CardReport, ChunkReport, utcnow
from app.repositories.base import Repository
from app.repositories.knowledge import HiddenChunk


class CardReportRepository(Repository):
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
