"""Queries for batches of suggested cards."""

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AiGeneration


class GenerationRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def add(self, generation: AiGeneration) -> AiGeneration:
        self.session.add(generation)
        await self.session.flush()
        return generation

    async def get_owned(
        self, generation_id: int, user_id: int, *, lock: bool = False
    ) -> AiGeneration | None:
        """`lock` holds the row until the commit, so two decisions run one after the other."""
        statement = select(AiGeneration).where(
            AiGeneration.id == generation_id, AiGeneration.user_id == user_id
        )
        if lock:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def get_for_job(self, job_id: int) -> AiGeneration | None:
        return await self.session.scalar(select(AiGeneration).where(AiGeneration.job_id == job_id))

    async def count_with_cards_since(self, user_id: int, since: datetime) -> int:
        """A batch with no cards gave the learner nothing, so it doesn't use their allowance."""
        return await self.session.scalar(
            select(func.count())
            .select_from(AiGeneration)
            .where(
                AiGeneration.user_id == user_id,
                AiGeneration.created_at > since,
                AiGeneration.empty.is_(False),
            )
        )
