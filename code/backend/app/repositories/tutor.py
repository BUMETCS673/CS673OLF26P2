"""Queries for tutor conversations."""

import uuid
from datetime import datetime

from sqlalchemy import and_, or_, select, update
from sqlalchemy.dialects.postgresql import insert

from app.models import TutorConversation, utcnow
from app.models.tutor import IDLE, REPLYING
from app.repositories.base import Repository


class TutorRepository(Repository):
    async def for_deck(self, deck_id: int, *, lock: bool = False) -> TutorConversation | None:
        statement = select(TutorConversation).where(TutorConversation.deck_id == deck_id)
        if lock:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def get_or_create(self, deck_id: int, user_id: int) -> TutorConversation:
        """On a conflict, a simultaneous request created it first, so this reads that one."""
        await self.session.execute(
            insert(TutorConversation)
            .values(deck_id=deck_id, user_id=user_id, thread_id=str(uuid.uuid4()))
            .on_conflict_do_nothing(index_elements=["deck_id"])
        )
        return await self.for_deck(deck_id)

    async def claim(self, conversation: TutorConversation, stale_before: datetime) -> bool:
        """Move idle to replying. The conditional update lets only one request succeed."""
        result = await self.session.execute(
            update(TutorConversation)
            .where(
                TutorConversation.id == conversation.id,
                or_(
                    TutorConversation.status == IDLE,
                    and_(
                        TutorConversation.status == REPLYING,
                        TutorConversation.status_at < stale_before,
                    ),
                ),
            )
            .values(status=REPLYING, status_at=utcnow())
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            return False
        # The update skipped the session, and setting a value it thinks is unchanged writes nothing.
        await self.session.refresh(conversation)
        return True

    async def delete(self, conversation: TutorConversation) -> None:
        await self.session.delete(conversation)
