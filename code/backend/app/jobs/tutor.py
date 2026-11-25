"""The job that runs one tutor turn, queued by the tutor's message route."""

from langchain_core.stores import ByteStore

from app.core.settings import Settings
from app.jobs.execution import JobContext
from app.services.budget import BudgetService
from app.services.tutor import TutorService


async def run_tutor_turn(
    context: JobContext, settings: Settings, cache: ByteStore | None = None
) -> None:
    """The page reads the saved chat once the job is done, so the result holds nothing."""
    # one session for the turn, which the service commits between steps to free its connection
    async with context.transaction() as tx:
        budget = BudgetService(tx.usage, settings)
        service = TutorService(tx.session, tx.tutor, tx.cards, tx.jobs, budget, settings, cache)
        payload = context.payload
        await service.run_turn(payload["deck_id"], context.user_id, payload["text"])
