"""The central knowledge base, shared by all users: its contents, from uploaded files and accepted
cards, and searching them.
"""

import hashlib
import logging
import threading
import time
from collections.abc import Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import timedelta
from functools import partial
from itertools import batched
from pathlib import Path

from flask import current_app
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError

from app.ai.chunking import SearchChunk, split_pages
from app.ai.provider import (
    AIRateLimited,
    AITransient,
    AIUnavailable,
    Provider,
    Role,
    get_provider,
    is_configured,
)
from app.ai.reading import UnreadableDocument, reader_for
from app.ai.topics import suggest_topics
from app.extensions import db
from app.models import Card, Document, DocumentChunk, as_utc, utcnow
from app.models.document import (
    EMBEDDING,
    FAILED,
    FINDING_TOPICS,
    PROCESSING,
    QUEUED,
    READING,
    READY,
)
from app.services.errors import BudgetExceeded
from app.services.usage import CAP_WINDOW, MATERIALS, record_usage, within_model_limits

logger = logging.getLogger(__name__)

UNREADABLE = "That file couldn't be read. It may be corrupt, password-protected or a scan."
NOT_PROCESSED = "That file couldn't be processed. Try uploading it again."
INTERRUPTED = "Processing that file was interrupted. Try uploading it again."

# Long enough for a queued document to wait behind large ones. A running job touches its document
# after every batch, so only a queued one sits this long without being lost.
STALE_AFTER = timedelta(minutes=10)

EMBED_BATCH_SIZE = 100
EMBED_WORKERS = 4
EMBED_ATTEMPTS = 3
EMBED_BACKOFF_SECONDS = 5  # doubles after each failed attempt
MAX_DOCUMENTS_AT_ONCE = 2  # per gunicorn worker. Bounds threads and memory on a small server.
SEARCH_LIMIT = 10
SEARCH_OVERFETCH = 3
MIN_SIMILARITY = 0.5  # a starting point: tune it against real files
NEAR_DUPLICATE_SIMILARITY = 0.97  # high, because "X is 5" and "X is 7" are also very close

_pool: ThreadPoolExecutor | None = None
_pool_lock = threading.Lock()


def _embed_batch(embedder: Provider, batch: Sequence[SearchChunk]) -> list[list[float]]:
    """Runs on a pool thread, so it must not touch the database or Flask."""
    for attempt in range(EMBED_ATTEMPTS - 1):
        try:
            return embedder.embed([chunk.text for chunk in batch])
        except (AIRateLimited, AITransient):
            time.sleep(EMBED_BACKOFF_SECONDS * 2**attempt)
    return embedder.embed([chunk.text for chunk in batch])


def _save_batch(
    document: Document, batch: Sequence[SearchChunk], vectors: Sequence[list[float]]
) -> None:
    insert = postgres_insert if db.engine.dialect.name == "postgresql" else sqlite_insert
    # A retry can overlap a job that outlived its stale check, so a saved chunk isn't an error.
    statement = insert(DocumentChunk).on_conflict_do_nothing(
        index_elements=["document_id", "chunk_index"]
    )
    db.session.execute(
        statement,
        [
            {
                "document_id": document.id,
                "chunk_index": chunk.index,
                "page": chunk.page,
                "text": chunk.text,
                "embedding": vector,
                "embedding_model": document.embedding_model,
            }
            for chunk, vector in zip(batch, vectors, strict=True)
        ],
    )
    document.chunks_done += len(batch)
    db.session.commit()


def embed_chunks(document: Document, chunks: Iterable[SearchChunk], embedder: Provider) -> None:
    """Embed and save `chunks`, skipping saved ones, so a retry resumes where the last one failed.

    Each batch is committed as it finishes. Raises AIRateLimited or AIUnavailable when a batch
    keeps failing, and the batches saved before that stay saved.
    """
    # Vectors from different models can't be compared, so a new model starts again.
    if document.embedding_model not in (None, embedder.name):
        db.session.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document.id))
    document.embedding_model = embedder.name

    saved = set(
        db.session.scalars(
            select(DocumentChunk.chunk_index).where(DocumentChunk.document_id == document.id)
        )
    )
    document.chunks_done = len(saved)
    db.session.commit()

    pending = (chunk for chunk in chunks if chunk.index not in saved)
    embed = partial(_embed_batch, embedder)
    with ThreadPoolExecutor(max_workers=EMBED_WORKERS) as pool:
        # One group at a time, so at most EMBED_WORKERS batches wait in memory.
        for group in batched(batched(pending, EMBED_BATCH_SIZE), EMBED_WORKERS):
            for batch, vectors in zip(group, pool.map(embed, group), strict=True):
                _save_batch(document, batch, vectors)


def _set_stage(document: Document, stage: str) -> None:
    document.stage = stage
    db.session.commit()


def _failure_message(error: Exception) -> str:
    """Only messages written for the learner. Other errors' text can carry the file's content."""
    if isinstance(error, UnreadableDocument):
        return UNREADABLE
    if isinstance(error, AIRateLimited | AIUnavailable):
        return error.message
    return NOT_PROCESSED


def process_document(document_id: int, path: str, mime_type: str) -> None:
    """Read, split, embed and find topics for an upload, then delete its temp file `path`.

    Runs off the request, so nothing is left to catch an error: every failure ends up on the
    document, for the upload screen to show.
    """
    document = db.session.get(Document, document_id)
    writer = embedder = None
    try:
        reader = reader_for(mime_type)
        _set_stage(document, READING)
        # All in memory, because the progress display needs the total before embedding starts.
        chunks = list(split_pages(reader.pages(path)))
        if not chunks:
            raise UnreadableDocument()
        document.chunks_total = len(chunks)
        _set_stage(document, EMBEDDING)
        embedder = get_provider(Role.EMBEDDER)
        embed_chunks(document, chunks, embedder)

        _set_stage(document, FINDING_TOPICS)
        writer = get_provider()
        document.suggested_topics = suggest_topics(
            reader.headings(path), [chunk.text for chunk in chunks], writer
        )
        document.status, document.error = READY, None  # a job can outlive its stale check
    except Exception as error:
        # The type only (rule 17): a database error's text would include the chunk being saved.
        logger.warning("materials outcome=failed type=%s", type(error).__name__)
        db.session.rollback()
        document.status = FAILED
        document.error = _failure_message(error)
    finally:
        Path(path).unlink(missing_ok=True)
    record_usage(MATERIALS, document.user_id, None, writer, embedder=embedder)
    db.session.commit()


def _job_pool() -> ThreadPoolExecutor:
    """Built on first use, inside the gunicorn worker, because threads don't survive a fork."""
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = ThreadPoolExecutor(max_workers=MAX_DOCUMENTS_AT_ONCE)
        return _pool


def start_processing(document_id: int, path: str, mime_type: str) -> None:
    """Queue process_document(). Extra uploads wait for a free slot, so requests stay free.

    The queue is in memory, so a restart loses it. The upload route's stale check covers that.
    """
    if current_app.config["AI_MATERIALS_RUN_INLINE"]:
        process_document(document_id, path, mime_type)
        return
    app = current_app._get_current_object()

    def target():
        try:
            with app.app_context():
                process_document(document_id, path, mime_type)
        except Exception as error:  # the pool would otherwise hide this
            logger.warning("materials outcome=job_crashed type=%s", type(error).__name__)

    _job_pool().submit(target)


def fail_if_stale(document: Document) -> None:
    """Give up on a document no job has touched for a while, since a restart loses the queue.

    If its job turns out to be alive, it can still finish and mark the document ready.
    """
    if document.status == PROCESSING and as_utc(document.updated_at) < utcnow() - STALE_AFTER:
        document.status, document.error = FAILED, INTERRUPTED
        db.session.commit()


@dataclass(frozen=True)
class FoundChunk:
    id: int
    page: int | None
    text: str
    similarity: float  # 1 is the same direction, so closest in meaning


def search_chunks(
    embedder: Provider,
    query: str,
    document_id: int | None = None,
    limit: int = SEARCH_LIMIT,
) -> list[FoundChunk]:
    """The chunks closest to `query`, best first, leaving out anything too far away.

    Searches the whole knowledge base, or only `document_id`, which the caller has already checked
    the user may use. Needs Postgres: SQLite has no vectors. Raises AIRateLimited or AIUnavailable
    if the query can't be embedded.
    """
    vector = embedder.embed([query], is_query=True)[0]
    distance = DocumentChunk.embedding.cosine_distance(vector)
    statement = (
        select(DocumentChunk, distance.label("distance"))
        .where(
            DocumentChunk.embedding_model == embedder.name,  # other models' can't be compared
            distance <= 1 - MIN_SIMILARITY,
        )
        .order_by(distance)
        # Extra rows, because the same file from two users gives identical chunks.
        .limit(limit * SEARCH_OVERFETCH)
    )
    if document_id is not None:
        statement = statement.where(DocumentChunk.document_id == document_id)

    found, seen = [], set()
    for chunk, found_distance in db.session.execute(statement):
        if chunk.text not in seen and len(found) < limit:
            seen.add(chunk.text)
            found.append(FoundChunk(chunk.id, chunk.page, chunk.text, 1 - found_distance))
    return found


def _is_already_known(vector: list[float], model: str) -> bool:
    """Whether the knowledge base holds nearly the same text. SQLite has no vectors to compare."""
    if db.engine.dialect.name != "postgresql":
        return False
    close = DocumentChunk.embedding.cosine_distance(vector) <= 1 - NEAR_DUPLICATE_SIMILARITY
    return db.session.scalar(
        select(DocumentChunk.id).where(DocumentChunk.embedding_model == model, close).limit(1)
    ) is not None


def add_cards_to_knowledge_base(user_id: int, cards: Sequence[Card]) -> None:
    """Copy accepted cards into the knowledge base, skipping facts it already holds.

    Never raises, because the cards are already saved, and the learner shouldn't see an error for
    something that only helps later searches.
    """
    if not cards or not is_configured(Role.EMBEDDER):
        return
    embedder = None
    try:
        if not within_model_limits({Role.EMBEDDER: 1}):
            return
        embedder = get_provider(Role.EMBEDDER)
        texts = [f"{card.front} {card.back}" for card in cards]
        vectors = embedder.embed(texts)
        for card, text, vector in zip(cards, texts, vectors, strict=True):
            if not _is_already_known(vector, embedder.name):
                # Added one at a time, so a batch's own repeats count as already known.
                db.session.add(DocumentChunk(
                    source_card_id=card.id, text=text, embedding=vector,
                    embedding_model=embedder.name,
                ))
                db.session.flush()
        record_usage(MATERIALS, user_id, None, None, embedder=embedder)
        db.session.commit()
    except Exception as error:
        logger.warning("materials outcome=card_copy_failed type=%s", type(error).__name__)
        db.session.rollback()


def _check_upload_caps(user_id: int) -> None:
    """The learner's new files, then room on each model. Budgets are best effort.

    A file's embedding calls aren't known until it's read, so this only checks for some room.
    """
    limit = current_app.config["AI_MATERIALS_USER_DAILY_LIMIT"]
    recent = select(func.count()).select_from(Document).where(
        Document.user_id == user_id, Document.created_at > utcnow() - CAP_WINDOW
    )
    if db.session.scalar(recent) >= limit:
        raise BudgetExceeded(f"You've reached the limit of {limit} new files in 24 hours.")
    if not within_model_limits({Role.EMBEDDER: 1, Role.WRITER: 1}):
        raise BudgetExceeded("File processing has hit today's limit. Try again later.")


def accept_upload(
    user_id: int, filename: str, path: str, mime_type: str
) -> tuple[Document, bool]:
    """Start processing the temp file at `path`, unless this user already has that file.

    Returns the document, and whether processing started. Takes ownership of the temp file.
    """
    with open(path, "rb") as file:
        content_hash = hashlib.file_digest(file, "sha256").hexdigest()
    existing = select(Document).where(
        Document.user_id == user_id, Document.content_hash == content_hash
    )
    document = db.session.scalar(existing)
    if document is not None:
        fail_if_stale(document)
    if document is not None and document.status != FAILED:
        Path(path).unlink(missing_ok=True)
        return document, False

    if document is None:
        try:
            _check_upload_caps(user_id)
        except BudgetExceeded:
            Path(path).unlink(missing_ok=True)
            raise
        document = Document(user_id=user_id, filename=filename, content_hash=content_hash)
        db.session.add(document)
    else:
        # A retry: saved chunks get skipped, and it doesn't count as a new file.
        document.status, document.stage, document.error = PROCESSING, QUEUED, None
        document.filename = filename
    try:
        db.session.commit()
    except IntegrityError:  # the same file, uploaded twice at once
        db.session.rollback()
        Path(path).unlink(missing_ok=True)
        return db.session.scalar(existing), False

    start_processing(document.id, path, mime_type)
    return document, True
