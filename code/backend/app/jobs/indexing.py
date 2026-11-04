"""The job that makes an uploaded file searchable: read, split, embed, and find topics.

A retry repeats the whole run, but `aindex` skips chunks that are already saved, so it only pays
for what's missing. Failures are saved on the job, and the document picks them up from there.
"""

import asyncio
import tempfile
from functools import partial
from typing import Any

from langchain_core.documents import Document as Chunk
from langchain_core.stores import ByteStore
from sqlalchemy.ext.asyncio import AsyncEngine

from app.ai.knowledge.indexing import (
    add_source,
    chunk_id,
    create_record_manager,
    index_chunks,
    with_embedding_cache,
)
from app.ai.knowledge.loaders import HeadingLoader, UnreadableDocument, loader_for
from app.ai.knowledge.screening import (
    MAX_SCREEN_CALLS,
    looks_like_instructions,
    screen_chunks,
)
from app.ai.knowledge.splitting import split_pages
from app.ai.knowledge.store import create_store
from app.ai.knowledge.topics import suggest_topics
from app.ai.models import Role, load_chat_model, load_embeddings, model_name
from app.ai.usage import RunUsage
from app.core.errors import InvalidRequest
from app.core.settings import Settings
from app.jobs.execution import JobContext
from app.models.document import EMBEDDING, FINDING_TOPICS, READING, READY, SCREENING
from app.repositories.documents import DocumentRepository
from app.repositories.jobs import JobRepository
from app.repositories.knowledge import KnowledgeRepository
from app.repositories.usage import UsageRepository
from app.repositories.users import UserRepository
from app.services.budget import MATERIALS, BudgetService

UNREADABLE = "That file couldn't be read. It may be corrupt, password-protected or a scan."

# Per worker process. Each one holds a whole file's chunks in memory.
_files_at_once = asyncio.Semaphore(2)


def _read(loader: HeadingLoader) -> tuple[list[Chunk], list[str]]:
    """In a thread, because parsing a large PDF would otherwise stall every job in this worker."""
    return split_pages(loader.lazy_load()), loader.headings()


async def _update(context: JobContext, document_id: int, **values: Any) -> None:
    """Save progress first, and only then tell whoever is following."""
    async with context.session_factory() as session:
        await DocumentRepository(session).update(document_id, **values)
        await session.commit()
    await context.report(values)


async def _load_file(context: JobContext, document_id: int, mime_type: str) -> tuple[list, list]:
    """Rebuild the file on disk a part at a time, since the loaders read from a path."""
    with tempfile.NamedTemporaryFile() as file:
        number = 0
        while True:
            # A short session per part, so a large file doesn't hold a connection throughout.
            async with context.session_factory() as session:
                part = await DocumentRepository(session).read_part(document_id, number)
            if part is None:
                break
            file.write(part)
            number += 1
        file.flush()

        loader = loader_for(mime_type, file.name)
        if loader is None:
            raise InvalidRequest(UNREADABLE, "file")
        try:
            chunks, headings = await asyncio.to_thread(_read, loader)
        except UnreadableDocument:
            raise InvalidRequest(UNREADABLE, "file") from None
    if not chunks:  # no text, such as a scanned PDF
        raise InvalidRequest(UNREADABLE, "file")
    return chunks, headings


async def _screen(
    context: JobContext, document_id: int, settings: Settings, usage: RunUsage, chunks: list[Chunk]
) -> list[int]:
    """The positions of the clean chunks, now shared if the uploader's account is trusted.

    After saving, because a chunk's ID covers its metadata, and a retry's verdict can differ. A new
    account's clean chunks wait, and its next review after it becomes trusted shares them.
    """
    await _update(context, document_id, stage=SCREENING)
    async with context.session_factory() as session:
        budget = BudgetService(UsageRepository(session), settings)
        models = await budget.pick_models({Role.HELPER: MAX_SCREEN_CALLS})
    if models is None:  # the chunks stay private, which is safe
        return []
    clean = await screen_chunks(
        [chunk.page_content for chunk in chunks],
        partial(load_chat_model, Role.HELPER, settings, usage, models=models),
    )
    async with context.session_factory() as session:
        trusted = await UserRepository(session).is_trusted(context.user_id)
        await KnowledgeRepository(session).mark_screened(
            [chunk_id(chunks[i]) for i in clean], share=trusted
        )
        await session.commit()
    return clean


async def _index(
    context: JobContext,
    engine: AsyncEngine,
    settings: Settings,
    cache: ByteStore,
    usage: RunUsage,
) -> dict[str, Any] | None:
    document_id = context.payload["document_id"]
    async with context.session_factory() as session:
        document = await DocumentRepository(session).get(document_id)
    if document is None:  # deleted while it waited
        return None
    if document.status == READY:  # an earlier attempt finished, then its worker died
        return {"document_id": document_id, "chunks": document.chunks_total}

    await _update(context, document_id, stage=READING)
    chunks, headings = await _load_file(context, document_id, document.mime_type)

    model = model_name(Role.EMBEDDER, settings)
    add_source(chunks, embedding_model=model, owner_id=document.user_id, document_id=document_id)
    await _update(
        context,
        document_id,
        stage=EMBEDDING,
        embedding_model=model,
        chunks_total=len(chunks),
        chunks_done=0,
    )

    async def progress(done: int, _total: int) -> None:
        async with context.session_factory() as session:
            await DocumentRepository(session).raise_chunks_done(document_id, done)
            await session.commit()
        await context.report({"chunks_done": done})

    embeddings = with_embedding_cache(load_embeddings(settings, usage), cache, model)
    await index_chunks(
        chunks,
        await create_store(engine, embeddings),
        await create_record_manager(engine),
        progress,
    )

    clean = await _screen(context, document_id, settings, usage, chunks)

    await _update(context, document_id, stage=FINDING_TOPICS)
    async with context.session_factory() as session:
        budget = BudgetService(UsageRepository(session), settings)
        models = await budget.pick_models({Role.HELPER: 1})  # None tries the whole chain
    # Only what passed screening, so a file's injected text can't shape the options a learner sees.
    topics = await suggest_topics(
        [heading for heading in headings if not looks_like_instructions(heading)],
        [chunks[position].page_content for position in clean],
        partial(load_chat_model, Role.HELPER, settings, usage, models=models),
    )

    # The chunks now hold the text, so the original only costs storage. A failed file keeps its
    # parts, so a retry doesn't need another upload.
    async with context.session_factory() as session:
        # A retry that took over may be reading the parts, and it will finish the file itself.
        if context.attempt is not None and not await JobRepository(session).holds_attempt(
            context.job_id, context.attempt
        ):
            return None
        documents = DocumentRepository(session)
        await documents.update(
            document_id, status=READY, suggested_topics=topics, chunks_done=len(chunks), error=None
        )
        await documents.delete_parts(document_id)
        await session.commit()
    return {"document_id": document_id, "chunks": len(chunks)}


async def index_material(
    context: JobContext, engine: AsyncEngine, settings: Settings, cache: ByteStore
) -> dict[str, Any] | None:
    usage = RunUsage()
    async with _files_at_once:
        try:
            return await _index(context, engine, settings, cache, usage)
        finally:
            # A failed run still spent its quota.
            async with context.session_factory() as session:
                budget = BudgetService(UsageRepository(session), settings)
                budget.record(MATERIALS, context.user_id, None, usage)
                await session.commit()
