"""Accepting uploaded study files, which are saved in Postgres and indexed by a background job."""

import hashlib
import logging
from pathlib import Path
from typing import Protocol

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.knowledge.loaders import PDF
from app.ai.models import Role
from app.core.errors import BudgetExceeded, InvalidRequest, found
from app.core.settings import Settings
from app.models import Document, Job, utcnow
from app.models.document import FAILED, PROCESSING, QUEUED
from app.models.job import FAILED as JOB_FAILED
from app.models.job import INDEX_MATERIAL
from app.repositories.documents import DocumentRepository
from app.repositories.jobs import JobRepository
from app.schemas.materials import MaterialRead
from app.services.budget import BUDGET_WINDOW, BudgetService

logger = logging.getLogger(__name__)

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
    # Step 1: read the first bytes then rewind for the next reader
    start = await file.read(5)  # 5 bytes is enough for the PDF signature
    await file.seek(0)
    # Step 2: refuse an empty file and a "PDF" that doesn't start like one
    if not start:
        raise _invalid("That file is empty.")  # 422 to the client
    # check the magic bytes since the extension alone can lie
    if mime_type == PDF and start != b"%PDF-":
        raise _invalid("That file isn't a valid PDF.")  # 422


async def _measure(file: UploadedFile) -> tuple[str, int]:
    """The file's hash and size, read a part at a time so a large file stays out of memory."""
    digest, size = hashlib.sha256(), 0
    while part := await file.read(PART_SIZE):  # 1 MB at a time never the whole file
        digest.update(part)  # SHA-256 streams giving the same hash as reading it all at once
        size += len(part)
    await file.seek(0)  # rewind so the parts can be saved from the start
    return digest.hexdigest(), size  # the hash finds a file this user already uploaded


class MaterialService:
    def __init__(
        self,
        session: AsyncSession,
        documents: DocumentRepository,
        jobs: JobRepository,
        budget: BudgetService,
        settings: Settings,
    ):
        self.session = session  # one request's transaction so nothing saves until commit
        self.documents = documents
        self.jobs = jobs
        self.budget = budget
        self.settings = settings

    async def get(self, document_id: int, user_id: int) -> MaterialRead:
        # Step 1: load the user's file
        document = found(await self.documents.get_owned(document_id, user_id), MATERIAL_NOT_FOUND)
        # Step 2: settle a file whose job died so the page stops waiting on it
        await self._fail_if_job_failed(document)
        return MaterialRead.model_validate(document)  # the page polls this for the stage

    async def _fail_if_job_failed(self, document: Document) -> None:
        """The job's row decides, since a job can end without its handler running, such as when a
        worker dies on the last attempt.
        """
        # Step 1: only a file still processing can be stuck
        if document.status != PROCESSING:  # ready or failed has nothing to settle so no query
            return
        # Step 2: mark it failed if its job is gone or failed with the job's error if any
        job = await self.jobs.get(document.job_id) if document.job_id else None
        if job is None or job.status == JOB_FAILED:  # the job's row is the source of truth
            document.status = FAILED  # a failed file can be uploaded again as a retry
            document.error = job.error if job and job.error else INTERRUPTED  # a reason to show
            await self.session.commit()
            logger.info(
                "file marked failed",
                extra={"document_id": document.id, "job_found": job is not None},
            )

    async def _check_caps(self, user_id: int) -> None:
        """A file's embedding calls aren't known until it's read, so this only checks for room."""
        # Step 1: refuse once the user has added today's limit of new files
        limit = self.settings.ai_materials_user_daily_limit
        since = utcnow() - BUDGET_WINDOW  # rolling 24 hours not a calendar day
        if await self.documents.count_new_since(user_id, since) >= limit:
            logger.info("upload refused", extra={"user_id": user_id, "limit": "user"})
            raise BudgetExceeded(f"You've reached the limit of {limit} new files in 24 hours.")
        # Step 2: refuse if the embedder or the helper has no room left today
        # 1 call each is just room to start and the job checks again as it goes
        if not await self.budget.within_model_limits({Role.EMBEDDER: 1, Role.HELPER: 1}):
            logger.info("upload refused", extra={"user_id": user_id, "limit": "site"})
            raise BudgetExceeded("File processing has hit today's limit. Try again later.")  # 429

    async def _start_indexing(self, document: Document) -> None:
        job = await self.jobs.add(  # an outbox row sent to the queue only after commit
            Job(
                user_id=document.user_id,
                kind=INDEX_MATERIAL,
                payload={"document_id": document.id},  # the worker reads the parts by this id
            )
        )
        document.job_id = job.id  # links the file to its job to settle it if the job dies

    async def upload(
        self, user_id: int, filename: str, file: UploadedFile
    ) -> tuple[MaterialRead, bool]:
        """Save a file and queue its indexing. Returns it, and whether indexing started.

        The file, its parts and its job commit together, so there's never a file with no job.
        """
        # Step 1: check the name, the type by extension, the first bytes and the size
        if len(filename) > FILE_NAME_MAX:  # the column is VARCHAR(255)
            raise _invalid(f"The file name must be at most {FILE_NAME_MAX} characters.")  # 422
        # by extension since browsers disagree on a Markdown file's type
        mime_type = TYPES_BY_EXTENSION.get(Path(filename).suffix.lower())
        if mime_type is None:
            logger.info("upload refused", extra={"user_id": user_id, "reason": "unsupported_type"})
            raise _invalid(UNSUPPORTED_FILE)  # 422
        await _check_content(file, mime_type)  # cheap checks before reading the whole file
        content_hash, size = await _measure(file)  # one streamed pass for both
        if size > FILE_MAX:  # 50 MB
            logger.info("upload refused", extra={"user_id": user_id, "reason": "too_large"})
            raise _invalid(FILE_TOO_LARGE)  # 422

        # Step 2: the same file uploaded before is returned as it is unless it failed
        # dedupe by content hash so a renamed copy is still the same file
        document = await self.documents.get_by_hash(user_id, content_hash)
        if document is not None:
            await self._fail_if_job_failed(document)  # a stuck one becomes FAILED so it retries
        if document is not None and document.status != FAILED:  # processing or ready
            logger.info(
                "upload matched existing file",
                extra={"document_id": document.id, "status": document.status},
            )
            return MaterialRead.model_validate(document), False  # 200 with no new work

        retry = document is not None
        if retry:
            # Step 3a: retry a failed file whose parts are already saved without counting it as a
            # new file
            document.status, document.stage, document.error = PROCESSING, QUEUED, None  # reset
            document.filename = filename  # keep the name it was uploaded with this time
        else:
            # Step 3b: a new file Check the limits then save it and its parts
            await self._check_caps(user_id)  # only new files count against the daily limit
            try:
                document = await self.documents.add(
                    Document(
                        user_id=user_id,
                        filename=filename,
                        content_hash=content_hash,
                        mime_type=mime_type,
                        size_bytes=size,
                    )
                )  # flushed so the parts below can point at its id
            # a race where unique (user_id, content_hash) rejected the second upload
            except IntegrityError:
                await self.session.rollback()  # the failed INSERT spoiled the transaction
                existing = await self.documents.get_by_hash(user_id, content_hash)
                return MaterialRead.model_validate(existing), False  # 200 with the winner's file
            number = 0
            # 1 MB rows in Postgres so no file storage service and no whole file in memory
            while part := await file.read(PART_SIZE):
                await self.documents.add_part(document.id, number, part)
                number += 1  # part order to put the file back together

        # Step 4: queue its indexing job committed with the file
        await self._start_indexing(document)
        await self.session.commit()  # file, parts and job together so never a file with no job
        logger.info(
            "upload queued",
            extra={
                "document_id": document.id,
                "job_id": document.job_id,
                "size_bytes": size,
                "mime_type": mime_type,
                "retry": retry,
            },
        )
        return MaterialRead.model_validate(document), True  # 202 since indexing started
