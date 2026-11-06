"""One session and the repositories that share it."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import cached_property

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.repositories.card_reports import CardReportRepository
from app.repositories.cards import CardRepository
from app.repositories.decks import DeckRepository
from app.repositories.documents import DocumentRepository
from app.repositories.generations import GenerationRepository
from app.repositories.jobs import JobRepository
from app.repositories.knowledge import KnowledgeRepository
from app.repositories.problem_cards import ProblemCardRepository
from app.repositories.tutor import TutorRepository
from app.repositories.usage import UsageRepository
from app.repositories.users import UserRepository


class UnitOfWork:
    """Nothing is saved until `commit()`. Whoever made the session closes it."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()

    # cached_property builds each repository on first use and reuses it after that
    @cached_property
    def cards(self) -> CardRepository:
        return CardRepository(self.session)

    @cached_property
    def card_reports(self) -> CardReportRepository:
        return CardReportRepository(self.session)

    @cached_property
    def decks(self) -> DeckRepository:
        return DeckRepository(self.session)

    @cached_property
    def documents(self) -> DocumentRepository:
        return DocumentRepository(self.session)

    @cached_property
    def generations(self) -> GenerationRepository:
        return GenerationRepository(self.session)

    @cached_property
    def jobs(self) -> JobRepository:
        return JobRepository(self.session)

    @cached_property
    def knowledge(self) -> KnowledgeRepository:
        return KnowledgeRepository(self.session)

    @cached_property
    def problem_cards(self) -> ProblemCardRepository:
        return ProblemCardRepository(self.session)

    @cached_property
    def tutor(self) -> TutorRepository:
        return TutorRepository(self.session)

    @cached_property
    def usage(self) -> UsageRepository:
        return UsageRepository(self.session)

    @cached_property
    def users(self) -> UserRepository:
        return UserRepository(self.session)


@asynccontextmanager
async def open_unit_of_work(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[UnitOfWork]:
    """A new session that closes at the end of the block, for work outside a request."""
    async with session_factory() as session:  # closing rolls back anything not committed
        yield UnitOfWork(session)
