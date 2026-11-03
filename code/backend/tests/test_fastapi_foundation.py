"""The FastAPI app's settings, database session and health routes."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.core.database import get_session
from app.core.settings import Settings
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
