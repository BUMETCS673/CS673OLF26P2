"""The job that makes an uploaded file searchable: read, split, embed, and find topics.

A retry repeats the whole run, but `aindex` skips chunks that are already saved, so it only pays
for what's missing. Failures are saved on the job, and the document picks them up from there.
"""

import asyncio
import logging
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
from app.services.budget import MATERIALS, BudgetService

logger = logging.getLogger(__name__)

UNREADABLE = "That file couldn't be read. It may be corrupt, password-protected or a scan."

# Per worker process. Each one holds a whole file's chunks in memory.
_files_at_once = asyncio.Semaphore(2)  # bounds memory on the 512 MB plan


def _read(loader: HeadingLoader) -> tuple[list[Chunk], list[str]]:
    """In a thread, because parsing a large PDF would otherwise stall every job in this worker."""
    # lazy_load feeds the splitter one page at a time never the whole parsed file
    return split_pages(loader.lazy_load()), loader.headings()  # headings serve as topic hints


async def _update(context: JobContext, document_id: int, **values: Any) -> None:
    """Save progress first, and only then tell whoever is following."""
    async with context.transaction() as tx:
        await tx.documents.update(document_id, **values)
        await tx.commit()  # the row first so a reload shows the same stage the event said
    await context.report(values)  # then the live event


async def _load_file(context: JobContext, document_id: int, mime_type: str) -> tuple[list, list]:
    """Rebuild the file on disk a part at a time, since the loaders read from a path."""
    with tempfile.NamedTemporaryFile() as file:  # deleted on close even on error
        number = 0
        # Step 1: copy the 1 MB parts from Postgres to a temp file in order
        while True:
            # A short session per part, so a large file doesn't hold a connection throughout.
            async with context.transaction() as tx:
                part = await tx.documents.read_part(document_id, number)
            if part is None:  # past the last part
                break
            file.write(part)  # only one part in memory at a time
            number += 1
        file.flush()  # make the bytes visible to the loader which reopens by name

        # Step 2: parse and split it in a thread
        loader = loader_for(mime_type, file.name)  # PDF or plain text loader
        if loader is None:
            raise InvalidRequest(UNREADABLE, "file")  # permanent since a retry won't help
        try:
            chunks, headings = await asyncio.to_thread(_read, loader)  # CPU work off the loop
        except UnreadableDocument:  # corrupt or password-protected
            raise InvalidRequest(UNREADABLE, "file") from None
    # Step 3: a file with no text can't be used
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
    # Step 1: check the helper has room for screening's worst case
    await _update(context, document_id, stage=SCREENING)
    async with context.transaction() as tx:
        budget = BudgetService(tx.usage, settings)
        models = await budget.pick_models({Role.HELPER: MAX_SCREEN_CALLS})  # at most 8 calls
    if models is None:  # the chunks stay private, which is safe
        logger.info("screening skipped", extra={"document_id": document_id, "reason": "no_budget"})
        return []
    # Step 2: ask the helper which chunks are plain material not instructions to a model
    clean = await screen_chunks(  # guards shared search against prompt injection in uploads
        [chunk.page_content for chunk in chunks],
        # partial makes a factory so each batch builds its model with the picked chain
        partial(load_chat_model, Role.HELPER, settings, usage, models=models),
    )
    # Step 3: mark the clean chunks screened and shared at once if the uploader is trusted
    async with context.transaction() as tx:
        trusted = await tx.users.is_trusted(context.user_id)
        await tx.knowledge.mark_screened(  # one UPDATE by id
            [chunk_id(chunks[i]) for i in clean], share=trusted  # same ids aindex saved them under
        )
        await tx.commit()
    return clean  # positions used to pick the text for topics


async def _index(
    context: JobContext,
    engine: AsyncEngine,
    settings: Settings,
    cache: ByteStore,
    usage: RunUsage,
) -> dict[str, Any] | None:
    document_id = context.payload["document_id"]
    # Step 1: load the file's row and stop if it's gone or already done
    async with context.transaction() as tx:
        document = await tx.documents.get(document_id)
    if document is None:  # deleted while it waited
        return None
    if document.status == READY:  # an earlier attempt finished, then its worker died
        return {"document_id": document_id, "chunks": document.chunks_total}

    # Step 2: read the file into chunks
    await _update(context, document_id, stage=READING)
    chunks, headings = await _load_file(context, document_id, document.mime_type)
    logger.info("file read", extra={"document_id": document_id, "chunks": len(chunks)})

    # Step 3: tag each chunk with where it came from and show the embedding stage
    model = model_name(Role.EMBEDDER, settings)
    # private to the uploader until screening says otherwise
    add_source(chunks, embedding_model=model, owner_id=document.user_id, document_id=document_id)
    await _update(
        context,
        document_id,
        stage=EMBEDDING,
        embedding_model=model,
        chunks_total=len(chunks),  # the page's progress bar total
        chunks_done=0,
    )

    async def progress(done: int, _total: int) -> None:  # called after each batch saves
        async with context.transaction() as tx:
            # GREATEST keeps the count from dropping when batches finish out of order
            await tx.documents.raise_chunks_done(document_id, done)
            await tx.commit()
        await context.report({"chunks_done": done})

    # Step 4: embed and save the chunks skipping any a previous attempt saved
    embeddings = with_embedding_cache(load_embeddings(settings, usage), cache, model)
    await index_chunks(  # 100 chunks per batch 4 batches at once
        chunks,
        await create_store(engine, embeddings),  # PGVectorStore with vector plus keyword search
        await create_record_manager(engine),  # remembers saved chunk ids so retries skip them
        progress,
    )

    # Step 5: screen the chunks for instructions aimed at a model
    clean = await _screen(context, document_id, settings, usage, chunks)

    # Step 6: suggest topics from the clean headings and chunks
    await _update(context, document_id, stage=FINDING_TOPICS)
    async with context.transaction() as tx:
        budget = BudgetService(tx.usage, settings)
        models = await budget.pick_models({Role.HELPER: 1})  # None tries the whole chain
    # Only what passed screening, so a file's injected text can't shape the options a learner sees.
    topics = await suggest_topics(
        [heading for heading in headings if not looks_like_instructions(heading)],  # cheap filter
        [chunks[position].page_content for position in clean],
        partial(load_chat_model, Role.HELPER, settings, usage, models=models),
    )

    # Step 7: mark the file ready and drop its raw parts
    # The chunks now hold the text, so the original only costs storage. A failed file keeps its
    # parts, so a retry doesn't need another upload.
    async with context.transaction() as tx:
        # A retry that took over may be reading the parts, and it will finish the file itself.
        # holds_attempt locks the job row so no retry can start until this commits
        if context.attempt is not None and not await tx.jobs.holds_attempt(
            context.job_id, context.attempt
        ):
            logger.info("file indexing yielded", extra={"document_id": document_id})
            return None
        documents = tx.documents
        await documents.update(
            document_id, status=READY, suggested_topics=topics, chunks_done=len(chunks), error=None
        )
        await documents.delete_parts(document_id)  # one DELETE for every part
        await tx.commit()  # ready and parts gone together
    logger.info(
        "file indexed",
        extra={
            "document_id": document_id,
            "chunks": len(chunks),
            "clean": len(clean),
            "topics": len(topics),
        },
    )
    return {"document_id": document_id, "chunks": len(chunks)}


async def index_material(
    context: JobContext, engine: AsyncEngine, settings: Settings, cache: ByteStore
) -> dict[str, Any] | None:
    usage = RunUsage()
    async with _files_at_once:  # a third file waits here instead of using more memory
        try:
            return await _index(context, engine, settings, cache, usage)
        finally:
            # A failed run still spent its quota.
            async with context.transaction() as tx:
                budget = BudgetService(tx.usage, settings)
                budget.record(MATERIALS, context.user_id, None, usage)
                await tx.commit()
