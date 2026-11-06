"""Queries for AI usage, which every budget reads from.

Each query matches one of the table's covering indexes, so Postgres sums `calls` from the index
alone, without visiting the table's rows.
"""

from collections.abc import Collection
from datetime import datetime

from sqlalchemy import func, select

from app.models import AiUsage
from app.repositories.base import Repository


def _total(*conditions):
    total = func.sum(AiUsage.calls)
    return func.coalesce(total.filter(*conditions) if conditions else total, 0)


class UsageRepository(Repository):
    def add(self, usage: AiUsage) -> None:
        self.session.add(usage)

    async def calls_by_model(self, models: Collection[str], since: datetime) -> dict[str, int]:
        """Every model's calls in one grouped query. A model with none is left out."""
        rows = await self.session.execute(
            select(AiUsage.model, func.sum(AiUsage.calls))
            .where(AiUsage.model.in_(models), AiUsage.created_at > since)
            .group_by(AiUsage.model)
        )
        return dict(rows.tuples().all())

    async def feature_calls(self, feature: str, since: datetime, user_id: int) -> tuple[int, int]:
        """The site's and one user's calls, from a single pass over the feature's window."""
        site, own = (
            await self.session.execute(
                select(_total(), _total(AiUsage.user_id == user_id)).where(
                    AiUsage.feature == feature, AiUsage.created_at > since
                )
            )
        ).one()
        return site, own

    async def user_feature_calls(self, feature: str, since: datetime, user_id: int) -> int:
        """Reads only this user's rows, for checks that have no site-wide limit."""
        return await self.session.scalar(
            select(_total()).where(
                AiUsage.user_id == user_id,
                AiUsage.feature == feature,
                AiUsage.created_at > since,
            )
        )
