"""Queries for uploaded files."""

from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Document, DocumentFilePart


class DocumentRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def add(self, document: Document) -> Document:
        self.session.add(document)
        await self.session.flush()
        return document

    async def add_part(self, document_id: int, number: int, data: bytes) -> None:
        """A plain insert, since a loaded object would keep the file's bytes in memory."""
        await self.session.execute(
            insert(DocumentFilePart).values(document_id=document_id, number=number, data=data)
        )

    async def read_part(self, document_id: int, number: int) -> bytes | None:
        return await self.session.scalar(
            select(DocumentFilePart.data).where(
                DocumentFilePart.document_id == document_id, DocumentFilePart.number == number
            )
        )

    async def delete_parts(self, document_id: int) -> None:
        await self.session.execute(
            delete(DocumentFilePart).where(DocumentFilePart.document_id == document_id)
        )

    async def get(self, document_id: int) -> Document | None:
        return await self.session.get(Document, document_id)

    async def update(self, document_id: int, **values: Any) -> None:
        await self.session.execute(
            update(Document).where(Document.id == document_id).values(**values)
        )

    async def raise_chunks_done(self, document_id: int, done: int) -> None:
        """Never lowers it, since batches running at once can save out of order."""
        await self.session.execute(
            update(Document)
            .where(Document.id == document_id)
            .values(chunks_done=func.greatest(Document.chunks_done, done))
        )

    async def get_owned(self, document_id: int, user_id: int) -> Document | None:
        return await self.session.scalar(
            select(Document).where(Document.id == document_id, Document.user_id == user_id)
        )

    async def get_by_hash(self, user_id: int, content_hash: str) -> Document | None:
        return await self.session.scalar(
            select(Document).where(
                Document.user_id == user_id, Document.content_hash == content_hash
            )
        )

    async def count_new_since(self, user_id: int, since: datetime) -> int:
        return await self.session.scalar(
            select(func.count())
            .select_from(Document)
            .where(Document.user_id == user_id, Document.created_at > since)
        )
