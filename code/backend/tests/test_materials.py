"""Uploading study files."""

import pytest
from sqlalchemy import func, select

from app.core.settings import get_settings
from app.models import Document, DocumentFilePart, Job
from app.models.document import FAILED, PROCESSING, QUEUED
from app.models.job import FAILED as JOB_FAILED
from app.models.job import INDEX_MATERIAL
from app.repositories.documents import DocumentRepository
from app.routers import materials as materials_router
from app.services import materials as materials_service
from app.services.budget import BudgetService

URL = "/api/materials"


async def _upload(client, data=b"Cells divide.", name="notes.txt"):
    return await client.post(URL, files={"file": (name, data, "application/octet-stream")})


async def _count(session, model) -> int:
    return await session.scalar(select(func.count()).select_from(model))


async def test_signing_in_is_required(client):
    assert (await _upload(client)).status_code == 401
    assert (await client.get(f"{URL}/1")).status_code == 401


async def test_an_upload_saves_the_file_and_queues_its_job(client, session, me):
    response = await _upload(client)

    assert response.status_code == 202
    body = response.json()
    assert (body["filename"], body["status"], body["stage"]) == ("notes.txt", PROCESSING, QUEUED)
    document = await session.get(Document, body["id"])
    assert (document.user_id, document.mime_type, document.size_bytes) == (me.id, "text/plain", 13)
    job = await session.get(Job, body["job_id"])
    assert (job.user_id, job.kind) == (me.id, INDEX_MATERIAL)
    assert job.payload == {"document_id": document.id}


@pytest.mark.parametrize(
    ("name", "data", "mime_type"),
    [
        ("notes.md", b"# Cells", "text/markdown"),
        ("NOTES.PDF", b"%PDF-1.7 rest", "application/pdf"),
    ],
)
async def test_the_type_comes_from_the_extension(client, session, me, name, data, mime_type):
    response = await _upload(client, data, name)

    assert (await session.get(Document, response.json()["id"])).mime_type == mime_type


async def test_a_file_is_saved_in_parts(client, session, me, monkeypatch):
    monkeypatch.setattr(materials_service, "PART_SIZE", 4)

    response = await _upload(client, b"0123456789")

    parts = await session.execute(
        select(DocumentFilePart.number, DocumentFilePart.data)
        .where(DocumentFilePart.document_id == response.json()["id"])
        .order_by(DocumentFilePart.number)
    )
    assert [tuple(part) for part in parts] == [(0, b"0123"), (1, b"4567"), (2, b"89")]


async def test_the_same_file_again_isnt_processed_again(client, session, me):
    first = await _upload(client)
    second = await _upload(client, name="renamed.txt")

    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["job_id"] == first.json()["job_id"]
    assert await _count(session, Job) == 1


async def test_two_users_each_get_their_own_copy(client, me, make_user, login_as):
    first = await _upload(client)
    await login_as(await make_user(email="other@example.com"))

    second = await _upload(client)

    assert second.status_code == 202
    assert second.json()["id"] != first.json()["id"]


async def test_a_failed_file_can_be_tried_again(client, session, me):
    first = (await _upload(client)).json()
    document = await session.get(Document, first["id"])
    document.status, document.error = FAILED, "It broke."
    await session.commit()

    response = await _upload(client)

    assert response.status_code == 202
    body = response.json()
    assert (body["id"], body["status"], body["error"]) == (first["id"], PROCESSING, None)
    assert body["job_id"] != first["job_id"]
    assert await _count(session, DocumentFilePart) == 1


@pytest.mark.parametrize(
    ("name", "data", "message"),
    [
        ("notes.docx", b"text", materials_service.UNSUPPORTED_FILE),
        ("notes.txt", b"", "That file is empty."),
        ("notes.pdf", b"not a pdf", "That file isn't a valid PDF."),
        ("n" * 252 + ".txt", b"text", "The file name must be at most 255 characters."),
    ],
)
async def test_a_bad_file_is_refused(client, session, me, name, data, message):
    response = await _upload(client, data, name)

    assert response.status_code == 422
    assert response.json()["error"]["field"] == "file"
    assert response.json()["error"]["message"] == message
    assert await _count(session, Document) == 0


async def test_a_missing_file_is_refused(client, me):
    assert (await client.post(URL, data={"other": "x"}, files={})).status_code == 422
    assert (await client.post(URL, json={"file": "x"})).status_code == 422


async def test_a_body_over_the_limit_stops_while_arriving(client, session, me, monkeypatch):
    monkeypatch.setattr(materials_router, "BODY_MAX", 100)

    response = await _upload(client, b"x" * 1000)

    assert response.status_code == 422
    assert response.json()["error"]["message"] == materials_service.FILE_TOO_LARGE
    assert await _count(session, Document) == 0


async def test_a_file_over_the_limit_is_refused(client, session, me, monkeypatch):
    monkeypatch.setattr(materials_service, "FILE_MAX", 5)

    response = await _upload(client, b"123456")

    assert response.status_code == 422
    assert await _count(session, Document) == 0


async def test_the_daily_limit_counts_new_files_only(client, me, monkeypatch):
    monkeypatch.setattr(get_settings(), "ai_materials_user_daily_limit", 1)
    await _upload(client, b"first")

    assert (await _upload(client, b"first")).status_code == 200
    response = await _upload(client, b"second")

    assert response.status_code == 429


async def test_a_full_model_limit_refuses_new_files(client, me, monkeypatch):
    async def full(*_, **__):
        return False

    monkeypatch.setattr(BudgetService, "within_model_limits", full)

    assert (await _upload(client)).status_code == 429


async def test_the_same_file_twice_at_once_gets_one_copy(client, session, me, monkeypatch):
    first = await _upload(client)
    real = DocumentRepository.get_by_hash
    misses = iter([None])

    # As if the other upload committed just after this one looked.
    async def miss_once(self, user_id, content_hash):
        try:
            return next(misses)
        except StopIteration:
            return await real(self, user_id, content_hash)

    monkeypatch.setattr(DocumentRepository, "get_by_hash", miss_once)

    second = await _upload(client)

    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert await _count(session, Document) == 1


async def test_a_failed_job_fails_its_file_with_the_jobs_message(client, session, me):
    body = (await _upload(client)).json()
    job = await session.get(Job, body["job_id"])
    job.status, job.error = JOB_FAILED, "It broke."
    await session.commit()

    response = await client.get(f"{URL}/{body['id']}")

    assert (response.json()["status"], response.json()["error"]) == (FAILED, "It broke.")


async def test_a_file_whose_job_is_alive_stays_processing(client, me):
    body = (await _upload(client)).json()

    response = await client.get(f"{URL}/{body['id']}")

    assert response.json()["status"] == PROCESSING


async def test_uploading_a_file_whose_job_failed_tries_again(client, session, me):
    body = (await _upload(client)).json()
    job = await session.get(Job, body["job_id"])
    job.status = JOB_FAILED
    await session.commit()

    response = await _upload(client)

    assert response.status_code == 202
    assert response.json()["job_id"] != body["job_id"]
    assert response.json()["status"] == PROCESSING


async def test_a_file_can_be_read(client, me):
    body = (await _upload(client)).json()

    response = await client.get(f"{URL}/{body['id']}")

    assert response.status_code == 200
    assert response.json()["filename"] == "notes.txt"


async def test_someone_elses_file_doesnt_exist(client, me, make_user, login_as):
    body = (await _upload(client)).json()
    await login_as(await make_user(email="other@example.com"))

    assert (await client.get(f"{URL}/{body['id']}")).status_code == 404
