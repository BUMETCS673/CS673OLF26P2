"""Embedding chunks and saving them to the knowledge base, safely repeatable."""

import asyncio
import hashlib
import json
import uuid
from collections.abc import Awaitable, Callable, Sequence
from itertools import batched

from langchain_classic.embeddings import CacheBackedEmbeddings
from langchain_classic.indexes import SQLRecordManager
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.indexing import aindex
from langchain_core.stores import ByteStore
from langchain_core.vectorstores import VectorStore
from sqlalchemy.ext.asyncio import AsyncEngine

from app.ai.models import AIRateLimited, AITransient, ai_errors

BATCH_SIZE = 100
CONCURRENT_BATCHES = 4
ATTEMPTS = 3
BACKOFF_SECONDS = 5  # doubles after each failed attempt

_NAMESPACE = "knowledge_chunks"
_ID_NAMESPACE = uuid.UUID("8f6f1f1e-6b1a-4c55-9d38-3f5c1a0b7d21")

Progress = Callable[[int, int], Awaitable[None]]


def chunk_id(chunk: Document) -> str:
    """A stable ID from a chunk's content and metadata.

    `aindex` uses this to recognize saved chunks. It must be a UUID, because that's the table's
    key, while `aindex`'s built-in strong hashes return plain hex.
    """
    fingerprint = json.dumps([chunk.page_content, chunk.metadata], sort_keys=True)
    digest = hashlib.sha256(fingerprint.encode()).hexdigest()
    return str(uuid.uuid5(_ID_NAMESPACE, digest))


def with_embedding_cache(embeddings: Embeddings, cache: ByteStore, model: str) -> Embeddings:
    """Reuse vectors for identical text, so a file many users upload is only embedded once."""
    return CacheBackedEmbeddings.from_bytes_store(
        embeddings, cache, namespace=model, key_encoder="sha256"
    )


async def create_record_manager(engine: AsyncEngine) -> SQLRecordManager:
    """Tracks what's been indexed. It creates its own table if needed."""
    manager = SQLRecordManager(_NAMESPACE, engine=engine)
    await manager.acreate_schema()
    return manager


def add_source(
    chunks: Sequence[Document], *, embedding_model: str, owner_id: int, document_id: int
) -> list[Document]:
    """Add the metadata columns that say where each chunk came from."""
    for chunk in chunks:
        chunk.metadata |= {
            "embedding_model": embedding_model,
            "owner_id": owner_id,
            "document_id": document_id,
        }
    return list(chunks)


async def _index_batch(
    batch: Sequence[Document], store: VectorStore, record_manager: SQLRecordManager
) -> None:
    for attempt in range(ATTEMPTS - 1):
        try:
            with ai_errors():
                await aindex(
                    batch, record_manager, store, batch_size=len(batch), key_encoder=chunk_id
                )
            return
        except (AIRateLimited, AITransient):
            await asyncio.sleep(BACKOFF_SECONDS * 2**attempt)
    with ai_errors():
        await aindex(batch, record_manager, store, batch_size=len(batch), key_encoder=chunk_id)


async def index_chunks(
    chunks: Sequence[Document],
    store: VectorStore,
    record_manager: SQLRecordManager,
    on_progress: Progress | None = None,
) -> None:
    """Save `chunks`, skipping any already saved, with a few batches running at once.

    Every batch runs to the end before an error is raised, so a retry only repeats what failed.
    Raises AIRateLimited or AIUnavailable when a batch keeps failing.
    """
    limit = asyncio.Semaphore(CONCURRENT_BATCHES)
    done = 0

    async def run(batch: Sequence[Document]) -> None:
        nonlocal done
        async with limit:
            await _index_batch(batch, store, record_manager)
            done += len(batch)
            if on_progress:
                await on_progress(done, len(chunks))

    batches = list(batched(chunks, BATCH_SIZE))
    results = await asyncio.gather(*(run(batch) for batch in batches), return_exceptions=True)
    for result in results:
        if isinstance(result, BaseException):
            raise result
