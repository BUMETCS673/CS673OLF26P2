"""The FastAPI app's settings, database session and health routes."""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.exc import OperationalError

from app.core.body_limit import BODY_MAX
from app.core.database import get_session
from app.core.settings import DEV_TOKEN_HASH_KEY, Settings
from app.main import app


@pytest.fixture
def client():
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("postgres://u:p@host/db", "postgresql+psycopg://u:p@host/db"),
        ("postgresql://u:p@host/db", "postgresql+psycopg://u:p@host/db"),
        ("postgresql+psycopg://u:p@host/db", "postgresql+psycopg://u:p@host/db"),
    ],
)
def test_the_database_url_always_uses_an_async_driver(url, expected):
    assert Settings(database_url=url).database_url == expected


def test_https_refuses_the_dev_token_key():
    with pytest.raises(ValidationError, match="TOKEN_HASH_KEY"):
        Settings(session_cookie_secure=True, token_hash_key=DEV_TOKEN_HASH_KEY)

    assert Settings(session_cookie_secure=True, token_hash_key="a-real-secret").token_hash_key


def test_a_body_over_the_limit_is_413(client):
    # streamed in chunks with no Content-Length, so only counting can catch it
    chunks = (b"x" * 65536 for _ in range(BODY_MAX // 65536 + 1))

    resp = client.post("/api/auth/login", content=chunks)

    assert resp.status_code == 413
    assert resp.json()["error"]["code"] == "too_large"


def test_liveness_needs_no_database(client):
    resp = client.get("/api/health")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_readiness_runs_a_query(client):
    queries = []

    class WorkingSession:
        async def execute(self, statement):
            queries.append(str(statement))

    async def working_session():
        yield WorkingSession()

    app.dependency_overrides[get_session] = working_session

    resp = client.get("/api/health/ready")

    assert resp.status_code == 200
    assert queries == ["SELECT 1"]


def test_readiness_is_503_when_the_database_is_unreachable(client):
    class BrokenSession:
        async def execute(self, statement):
            raise OperationalError("SELECT 1", {}, Exception("the private connection details"))

    async def broken_session():
        yield BrokenSession()

    app.dependency_overrides[get_session] = broken_session

    resp = client.get("/api/health/ready")

    assert resp.status_code == 503
    assert "private" not in resp.text
