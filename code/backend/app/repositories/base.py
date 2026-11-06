"""What every repository shares. Repositories flush and services commit."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import Base


class Repository:
    def __init__(self, session: AsyncSession):
        self.session = session  # every query runs in the caller's session and transaction


class ModelRepository[T: Base](Repository):
    """A repository for one table that adds new rows."""

    async def add(self, row: T) -> T:
        self.session.add(row)
        await self.session.flush()  # flush sends the INSERT now and fills in the row's id
        return row
