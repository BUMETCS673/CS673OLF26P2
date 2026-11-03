"""Turning a file's chunks into saved vectors."""

import threading

import pytest
from flask import has_app_context

from app.ai.chunking import SearchChunk
from app.ai.fake import FakeProvider
from app.ai.provider import NOT_CONFIGURED, AIRateLimited, AIUnavailable
from app.models import AiUsage, Document, DocumentChunk
from app.models.document import FAILED, READY
from app.services import materials
from app.services.materials import (
    EMBED_ATTEMPTS,
    EMBED_BATCH_SIZE,
    MAX_DOCUMENTS_AT_ONCE,
    NOT_PROCESSED,
    UNREADABLE,
    embed_chunks,
    process_document,
    start_processing,
)


class CountingEmbedder(FakeProvider):
    """Keeps the texts it was asked for, and raises `failures` first."""

    def __init__(self, failures=()):
        super().__init__()
        self.failures = list(failures)
        self.embedded = []
        self._lock = threading.Lock()

    def _embed(self, texts, is_query):
        with self._lock:
            if self.failures:
                raise self.failures.pop(0)
            self.embedded.extend(texts)
        return super()._embed(texts, is_query)


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    monkeypatch.setattr(materials.time, "sleep", lambda seconds: None)


@pytest.fixture
def document(db, make_user):
    row = Document(user_id=make_user().id, filename="notes.pdf", content_hash="a" * 64)
    db.session.add(row)
    db.session.commit()
    return row


def _chunks(count, start=0):
    return [SearchChunk(index, 1, f"chunk {index}") for index in range(start, start + count)]


def _saved_indexes():
    return sorted(chunk.chunk_index for chunk in DocumentChunk.query.all())


def test_every_chunk_is_saved_with_its_page_and_text(document):
    embed_chunks(document, [SearchChunk(0, 7, "Cells divide.")], FakeProvider())

    chunk = DocumentChunk.query.one()
    assert (chunk.document_id, chunk.page, chunk.text) == (document.id, 7, "Cells divide.")
    assert len(list(chunk.embedding)) > 0
    assert document.embedding_model == "fake"
    assert chunk.embedding_model == "fake"
    assert document.chunks_done == 1


def test_a_large_file_is_sent_in_batches(document):
    embedder = FakeProvider()

    embed_chunks(document, _chunks(EMBED_BATCH_SIZE * 2 + 1), embedder)

    assert embedder.usage.calls == 3
    assert _saved_indexes() == list(range(EMBED_BATCH_SIZE * 2 + 1))
    assert document.chunks_done == EMBED_BATCH_SIZE * 2 + 1


def test_a_retry_only_embeds_what_isnt_saved(document):
    embed_chunks(document, _chunks(3), FakeProvider())
    embedder = CountingEmbedder()

    embed_chunks(document, _chunks(5), embedder)

    assert embedder.embedded == ["chunk 3", "chunk 4"]
    assert _saved_indexes() == [0, 1, 2, 3, 4]
    assert document.chunks_done == 5


def test_a_rate_limit_waits_and_tries_again(document):
    embedder = CountingEmbedder(failures=[AIRateLimited()])

    embed_chunks(document, _chunks(2), embedder)

    assert _saved_indexes() == [0, 1]


def test_a_batch_that_keeps_failing_raises(document):
    embedder = CountingEmbedder(failures=[AIRateLimited() for _ in range(EMBED_ATTEMPTS)])

    with pytest.raises(AIRateLimited):
        embed_chunks(document, _chunks(1), embedder)

    assert _saved_indexes() == []


def test_an_error_that_retrying_wont_fix_raises_at_once(document):
    embedder = CountingEmbedder(failures=[AIUnavailable()])

    with pytest.raises(AIUnavailable):
        embed_chunks(document, _chunks(1), embedder)

    assert embedder.failures == []
    assert embedder.embedded == []


def test_a_new_model_replaces_the_old_models_vectors(db, document):
    embed_chunks(document, _chunks(2), FakeProvider())
    document.embedding_model = "an-older-model"
    db.session.commit()
    embedder = CountingEmbedder()

    embed_chunks(document, _chunks(2), embedder)

    assert embedder.embedded == ["chunk 0", "chunk 1"]
    assert document.embedding_model == "fake"
    assert _saved_indexes() == [0, 1]


# --- processing a whole file --------------------------------------------------------------


def _upload(tmp_path, data):
    path = tmp_path / "upload"
    path.write_bytes(data)
    return path


def _usage():
    return {row.role: row.calls for row in AiUsage.query.all()}


def test_a_file_ends_up_ready_with_chunks_and_topics(document, tmp_path):
    path = _upload(tmp_path, b"# Cells\nCells divide.\n## Enzymes\nEnzymes speed reactions.\n")

    process_document(document.id, str(path), "text/markdown")

    assert document.status == READY
    assert document.error is None
    assert document.suggested_topics == ["Cells", "Enzymes"]
    assert document.chunks_total == document.chunks_done == DocumentChunk.query.count() > 0


def test_headings_save_the_writers_call(document, tmp_path):
    path = _upload(tmp_path, b"# Cells\nCells divide.\n## Enzymes\nEnzymes speed reactions.\n")

    process_document(document.id, str(path), "text/markdown")

    assert _usage() == {"embedder": 1}


def test_a_file_with_no_headings_records_the_writers_call_too(document, tmp_path):
    process_document(document.id, str(_upload(tmp_path, b"Cells divide.\n")), "text/plain")

    assert document.suggested_topics
    assert _usage() == {"writer": 1, "embedder": 1}
    assert {row.feature for row in AiUsage.query.all()} == {"materials"}


def test_the_temp_file_is_deleted_after_success_and_failure(document, tmp_path):
    good = _upload(tmp_path, b"Cells divide.\n")
    process_document(document.id, str(good), "text/plain")
    assert not good.exists()

    bad = _upload(tmp_path, b"caf\xe9")
    process_document(document.id, str(bad), "text/plain")
    assert not bad.exists()


@pytest.mark.parametrize("data", [b"caf\xe9", b"", b"   \n"])
def test_a_file_with_no_readable_text_fails_with_a_message(document, tmp_path, data):
    process_document(document.id, str(_upload(tmp_path, data)), "text/plain")

    assert (document.status, document.error) == (FAILED, UNREADABLE)


def test_a_missing_embedding_setup_fails_with_its_message(app, document, tmp_path):
    app.config["AI_EMBEDDER_PROVIDER"] = "not-a-vendor"

    process_document(document.id, str(_upload(tmp_path, b"Cells.\n")), "text/plain")

    assert document.status == FAILED
    assert document.error == NOT_CONFIGURED


def test_an_unexpected_error_keeps_its_text_off_the_document(document, tmp_path, monkeypatch):
    def explode(*args):
        raise RuntimeError("the file's private content")

    monkeypatch.setattr(materials, "embed_chunks", explode)

    process_document(document.id, str(_upload(tmp_path, b"Cells.\n")), "text/plain")

    assert (document.status, document.error) == (FAILED, NOT_PROCESSED)


# --- the job pool ------------------------------------------------------------------------


def test_tests_process_a_file_in_the_request(document, tmp_path):
    start_processing(document.id, str(_upload(tmp_path, b"Cells.\n")), "text/plain")

    assert document.status == READY


def test_a_job_runs_on_another_thread_with_an_app_context(app, monkeypatch):
    app.config["AI_MATERIALS_RUN_INLINE"] = False
    seen, done = [], threading.Event()

    def record(*args):
        seen.append((args, threading.current_thread(), has_app_context()))
        done.set()

    monkeypatch.setattr(materials, "process_document", record)

    with app.app_context():
        start_processing(1, "path", "text/plain")

    assert done.wait(timeout=5)
    [(args, thread, had_context)] = seen
    assert args == (1, "path", "text/plain")
    assert thread is not threading.current_thread()
    assert had_context


def test_extra_uploads_wait_for_a_free_slot(app, monkeypatch):
    app.config["AI_MATERIALS_RUN_INLINE"] = False
    entered, finish = threading.Semaphore(0), threading.Event()

    def hold(*args):
        entered.release()
        finish.wait(timeout=5)

    monkeypatch.setattr(materials, "process_document", hold)

    with app.app_context():
        for document_id in range(MAX_DOCUMENTS_AT_ONCE + 1):
            start_processing(document_id, "path", "text/plain")

    for _ in range(MAX_DOCUMENTS_AT_ONCE):
        assert entered.acquire(timeout=5)
    assert not entered.acquire(timeout=0.2)
    finish.set()
    assert entered.acquire(timeout=5)


def test_a_crashed_job_is_logged_and_frees_its_slot(app, monkeypatch, caplog):
    app.config["AI_MATERIALS_RUN_INLINE"] = False
    done = threading.Event()

    def crash(*args):
        done.set()
        raise RuntimeError("the file's private content")

    monkeypatch.setattr(materials, "process_document", crash)

    with app.app_context():
        for _ in range(MAX_DOCUMENTS_AT_ONCE + 1):
            start_processing(1, "path", "text/plain")

    assert done.wait(timeout=5)
    materials._job_pool().submit(lambda: None).result(timeout=5)
    assert "materials outcome=job_crashed type=RuntimeError" in caplog.text
    assert "private content" not in caplog.text
