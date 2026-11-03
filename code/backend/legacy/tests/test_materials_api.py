"""POST /api/materials."""

import hashlib
import io
import tempfile
from datetime import timedelta

import pytest

from app.api import materials as materials_route
from app.models import AiUsage, Document, DocumentChunk, utcnow
from app.models.document import FAILED, PROCESSING, READY
from app.services.materials import INTERRUPTED, process_document


@pytest.fixture
def me(make_user, login_as):
    user = make_user(email="me@example.com")
    login_as(user)
    return user


@pytest.fixture(autouse=True)
def temp_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    return tmp_path


def _post(client, data=b"Cells divide.\n", name="notes.txt"):
    return client.post(
        "/api/materials",
        data={"file": (io.BytesIO(data), name)},
        content_type="multipart/form-data",
    )


def test_signing_in_is_required(client):
    assert _post(client).status_code == 401


def test_an_upload_starts_processing_and_returns_the_document(client, me):
    resp = _post(client)

    assert resp.status_code == 202
    body = resp.get_json()
    assert body["filename"] == "notes.txt"
    assert body["status"] == READY  # tests process in the request
    assert body["chunks_total"] == body["chunks_done"] == 1
    assert body["suggested_topics"]
    assert Document.query.one().user_id == me.id


def test_a_markdown_file_is_read_as_markdown(client, me):
    resp = _post(client, b"# Cells\ntext\n## Enzymes\ntext\n", "notes.MD")

    assert resp.get_json()["suggested_topics"] == ["Cells", "Enzymes"]


def test_the_same_file_again_is_not_processed_again(client, me):
    _post(client)
    calls = AiUsage.query.count()

    resp = _post(client, name="renamed.txt")

    assert resp.status_code == 200
    assert resp.get_json()["filename"] == "notes.txt"
    assert Document.query.count() == 1
    assert AiUsage.query.count() == calls


def test_two_users_each_get_their_own_copy(client, me, make_user, login_as):
    _post(client)
    login_as(make_user(email="other@example.com"))

    assert _post(client).status_code == 202
    assert Document.query.count() == 2
    assert DocumentChunk.query.count() == 2


def test_a_failed_file_can_be_tried_again(client, db, me):
    _post(client)
    document = Document.query.one()
    document.status, document.error = FAILED, "It failed."
    db.session.commit()

    resp = _post(client, name="again.txt")

    assert resp.status_code == 202
    body = resp.get_json()
    assert (body["status"], body["error"], body["filename"]) == (READY, None, "again.txt")


def test_a_file_that_cant_be_read_is_a_failed_document_not_an_error(client, me):
    resp = _post(client, b"caf\xe9")

    assert resp.status_code == 202
    assert resp.get_json()["status"] == FAILED
    assert resp.get_json()["error"]


@pytest.mark.parametrize(
    ("data", "name"),
    [
        (b"text", "photo.png"),
        (b"text", "no-extension"),
        (b"", "empty.txt"),
        (b"not a pdf", "fake.pdf"),
        (b"text", "x" * 256 + ".txt"),
    ],
)
def test_a_bad_file_is_refused_before_processing(client, me, data, name):
    resp = _post(client, data, name)

    assert resp.status_code == 422
    assert resp.get_json()["error"]["field"] == "file"
    assert Document.query.count() == 0


def test_a_missing_file_is_refused(client, me):
    resp = client.post("/api/materials", data={}, content_type="multipart/form-data")

    assert resp.status_code == 422


def test_a_body_over_the_limit_is_refused(client, me, monkeypatch):
    monkeypatch.setattr(materials_route, "BODY_MAX", 10)

    assert _post(client).status_code == 400
    assert Document.query.count() == 0


def test_a_file_over_the_limit_is_refused(client, me, monkeypatch):
    monkeypatch.setattr(materials_route, "FILE_MAX", 5)

    assert _post(client).status_code == 422


def test_the_daily_limit_counts_new_files_only(client, app, me):
    app.config["AI_MATERIALS_USER_DAILY_LIMIT"] = 1
    _post(client)

    assert _post(client).status_code == 200
    assert _post(client, b"Different.\n").status_code == 429
    assert Document.query.count() == 1


def test_a_full_model_limit_refuses_new_files(client, app, me):
    app.config["AI_MODEL_DAILY_LIMIT"] = 1  # both roles use "fake" here, and need 2 together

    assert _post(client).status_code == 429


@pytest.mark.parametrize(
    "scenario",
    ["processed", "repeat", "over_limit", "bad_content"],
)
def test_no_temp_file_is_left_behind(client, app, me, temp_dir, scenario):
    if scenario == "processed":
        _post(client)
    elif scenario == "repeat":
        _post(client)
        _post(client)
    elif scenario == "over_limit":
        app.config["AI_MATERIALS_USER_DAILY_LIMIT"] = 0
        _post(client)
    else:
        _post(client, b"not a pdf", "fake.pdf")

    assert list(temp_dir.glob("cadence-upload-*")) == []


# --- status ------------------------------------------------------------------------------


def _waiting_document(db, user, minutes_ago):
    """A document whose job hasn't touched it for `minutes_ago`."""
    document = Document(
        user_id=user.id,
        filename="notes.txt",
        content_hash=hashlib.sha256(b"Cells divide.\n").hexdigest(),
        updated_at=utcnow() - timedelta(minutes=minutes_ago),
    )
    db.session.add(document)
    db.session.commit()
    return document


def test_the_status_route_returns_the_document(client, me):
    document_id = _post(client).get_json()["id"]

    resp = client.get(f"/api/materials/{document_id}")

    assert resp.status_code == 200
    assert resp.get_json()["id"] == document_id
    assert resp.get_json()["status"] == READY


def test_the_status_route_needs_a_signed_in_user(client):
    assert client.get("/api/materials/1").status_code == 401


def test_a_missing_document_is_404(client, me):
    assert client.get("/api/materials/999").status_code == 404


def test_another_users_document_looks_missing(client, me, make_user, login_as):
    document_id = _post(client).get_json()["id"]
    login_as(make_user(email="other@example.com"))

    assert client.get(f"/api/materials/{document_id}").status_code == 404


def test_a_job_still_within_its_time_stays_processing(client, db, me):
    document = _waiting_document(db, me, minutes_ago=5)

    body = client.get(f"/api/materials/{document.id}").get_json()

    assert (body["status"], body["error"]) == (PROCESSING, None)


def test_an_abandoned_document_shows_as_failed(client, db, me):
    document = _waiting_document(db, me, minutes_ago=11)

    body = client.get(f"/api/materials/{document.id}").get_json()

    assert (body["status"], body["error"]) == (FAILED, INTERRUPTED)


def test_uploading_an_abandoned_file_again_retries_it(client, db, me):
    _waiting_document(db, me, minutes_ago=11)

    resp = _post(client)

    assert resp.status_code == 202
    assert resp.get_json()["status"] == READY


def test_a_job_that_outlives_its_stale_check_can_still_finish(client, db, me, tmp_path):
    document = _waiting_document(db, me, minutes_ago=11)
    client.get(f"/api/materials/{document.id}")
    path = tmp_path / "late"
    path.write_bytes(b"Cells divide.\n")

    process_document(document.id, str(path), "text/plain")

    body = client.get(f"/api/materials/{document.id}").get_json()
    assert (body["status"], body["error"]) == (READY, None)


def test_uploading_a_file_still_processing_doesnt_start_a_second_job(client, db, me):
    _waiting_document(db, me, minutes_ago=5)

    resp = _post(client)

    assert resp.status_code == 200
    assert resp.get_json()["status"] == PROCESSING
