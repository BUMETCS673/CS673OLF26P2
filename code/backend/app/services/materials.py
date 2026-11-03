"""Accepting uploaded study files, which are saved in Postgres and indexed by a background job."""

import hashlib
from pathlib import Path
from typing import Protocol

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.knowledge.loaders import PDF
from app.ai.models import Role
from app.core.errors import BudgetExceeded, InvalidRequest, NotFound
from app.core.settings import Settings
from app.models import Document, Job, utcnow
from app.models.document import FAILED, PROCESSING, QUEUED
from app.models.job import FAILED as JOB_FAILED
from app.models.job import INDEX_MATERIAL
from app.repositories.documents import DocumentRepository
from app.repositories.jobs import JobRepository
from app.schemas.materials import MaterialRead
from app.services.budget import BUDGET_WINDOW, BudgetService

MATERIAL_NOT_FOUND = "Document not found"
INTERRUPTED = "Processing that file was interrupted. Try uploading it again."
FILE_MAX = 50 * 1024 * 1024
FILE_TOO_LARGE = "The file must be 50 MB or smaller."
FILE_NAME_MAX = 255
PART_SIZE = 1024 * 1024  # small enough to hold one in memory, and to insert quickly

# By extension, because browsers disagree on the type of a Markdown file. The loader looks at the
# real content later.
TYPES_BY_EXTENSION = {".pdf": PDF, ".txt": "text/plain", ".md": "text/markdown"}
UNSUPPORTED_FILE = "Only PDF, TXT and MD files are supported. Save other documents as a PDF first."


class UploadedFile(Protocol):
    async def read(self, size: int = -1) -> bytes:
        """Up to `size` bytes, or the rest of the file when it's -1."""

    async def seek(self, offset: int) -> None:
        """Move to `offset` bytes from the start."""


def _invalid(message: str) -> InvalidRequest:
    return InvalidRequest(message, "file")


async def _check_content(file: UploadedFile, mime_type: str) -> None:
    start = await file.read(5)
    await file.seek(0)
    if not start:
        raise _invalid("That file is empty.")
    if mime_type == PDF and start != b"%PDF-":
        raise _invalid("That file isn't a valid PDF.")


async def _measure(file: UploadedFile) -> tuple[str, int]:
    """The file's hash and size, read a part at a time so a large file stays out of memory."""
    digest, size = hashlib.sha256(), 0
    while part := await file.read(PART_SIZE):
        digest.update(part)
        size += len(part)
    await file.seek(0)
    return digest.hexdigest(), size


class MaterialService:
    def __init__(
        self,
        session: AsyncSession,
        documents: DocumentRepository,
        jobs: JobRepository,
        budget: BudgetService,
        settings: Settings,
    ):
        self.session = session
        self.documents = documents
        self.jobs = jobs
        self.budget = budget
        self.settings = settings

    async def get(self, document_id: int, user_id: int) -> MaterialRead:
        document = await self.documents.get_owned(document_id, user_id)
        if document is None:
            raise NotFound(MATERIAL_NOT_FOUND)
        await self._fail_if_job_failed(document)
        return MaterialRead.model_validate(document)

    async def _fail_if_job_failed(self, document: Document) -> None:
        """The job's row decides, since a job can end without its handler running, such as when a
        worker dies on the last attempt.
        """
        if document.status != PROCESSING:
            return
        job = await self.jobs.get(document.job_id) if document.job_id else None
        if job is None or job.status == JOB_FAILED:
            document.status = FAILED
            document.error = job.error if job and job.error else INTERRUPTED
            await self.session.commit()

    async def _check_caps(self, user_id: int) -> None:
        """A file's embedding calls aren't known until it's read, so this only checks for room."""
        limit = self.settings.ai_materials_user_daily_limit
        since = utcnow() - BUDGET_WINDOW
        if await self.documents.count_new_since(user_id, since) >= limit:
            raise BudgetExceeded(f"You've reached the limit of {limit} new files in 24 hours.")
        if not await self.budget.within_model_limits({Role.EMBEDDER: 1, Role.WRITER: 1}):
            raise BudgetExceeded("File processing has hit today's limit. Try again later.")

    async def _start_indexing(self, document: Document) -> None:
        job = await self.jobs.add(
            Job(
                user_id=document.user_id,
                kind=INDEX_MATERIAL,
                payload={"document_id": document.id},
            )
        )
        document.job_id = job.id

    async def upload(
        self, user_id: int, filename: str, file: UploadedFile
    ) -> tuple[MaterialRead, bool]:
        """Save a file and queue its indexing. Returns it, and whether indexing started.

        The file, its parts and its job commit together, so there's never a file with no job.
        """
        if len(filename) > FILE_NAME_MAX:
            raise _invalid(f"The file name must be at most {FILE_NAME_MAX} characters.")
        mime_type = TYPES_BY_EXTENSION.get(Path(filename).suffix.lower())
        if mime_type is None:
            raise _invalid(UNSUPPORTED_FILE)
        await _check_content(file, mime_type)
        content_hash, size = await _measure(file)
        if size > FILE_MAX:
            raise _invalid(FILE_TOO_LARGE)

        document = await self.documents.get_by_hash(user_id, content_hash)
        if document is not None:
            await self._fail_if_job_failed(document)
        if document is not None and document.status != FAILED:
            return MaterialRead.model_validate(document), False

        if document is not None:
            # A retry: its parts are already saved, and it doesn't count as a new file.
            document.status, document.stage, document.error = PROCESSING, QUEUED, None
            document.filename = filename
        else:
            await self._check_caps(user_id)
            try:
                document = await self.documents.add(
                    Document(
                        user_id=user_id,
                        filename=filename,
                        content_hash=content_hash,
                        mime_type=mime_type,
                        size_bytes=size,
                    )
                )
            except IntegrityError:  # the same file, uploaded twice at once
                await self.session.rollback()
                existing = await self.documents.get_by_hash(user_id, content_hash)
                return MaterialRead.model_validate(existing), False
            number = 0
            while part := await file.read(PART_SIZE):
                await self.documents.add_part(document.id, number, part)
                number += 1

        await self._start_indexing(document)
        await self.session.commit()
        return MaterialRead.model_validate(document), True
