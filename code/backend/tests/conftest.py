"""Shared fixtures. Tests run against real Postgres with pgvector, from TEST_DATABASE_URL.

Each test runs inside a transaction that's rolled back afterward, so tests can't affect each
other, even though services commit: their commits only release a savepoint.
"""

import logging
import os
from datetime import timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.ai.checkpoints import close_checkpointers
from app.core.database import CONNECT_ARGS, get_session
from app.core.logs import FieldsFilter
from app.core.security import hash_session_token, new_session_token
from app.core.settings import Settings
from app.dependencies import SESSION_COOKIE
from app.main import app
from app.models import Base, Card, Deck, User, UserSession, utcnow
from app.repositories.users import UserRepository

_METRICS = InMemoryMetricReader()
# OpenTelemetry lets a process set its provider only once, so the whole run shares one.
metrics.set_meter_provider(MeterProvider(metric_readers=[_METRICS]))


@pytest.fixture
def logged(caplog):
    """caplog at DEBUG, its records carrying the fields our log handler adds."""
    caplog.handler.addFilter(FieldsFilter())
    caplog.set_level(logging.DEBUG)
    return caplog


@pytest.fixture
def metric_value():
    """A metric's current total for exactly these labels. Totals only grow, so compare two."""

    def _value(name: str, **labels: str) -> float:
        data = _METRICS.get_metrics_data()
        total = 0
        for resource in data.resource_metrics if data else []:
            for scope in resource.scope_metrics:
                for metric in scope.metrics:
                    if metric.name != name:
                        continue
                    for point in metric.data.data_points:
                        if dict(point.attributes) == labels:
                            # A counter's point has a value. A histogram's counts its records.
                            total += point.value if hasattr(point, "value") else point.count
        return total

    return _value


TEST_DATABASE_URL = Settings(
    database_url=os.environ.get(
        "TEST_DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/cadence_test"
    )
).database_url


@pytest.fixture(scope="session")
async def engine():
    engine = create_async_engine(TEST_DATABASE_URL, connect_args=CONNECT_ARGS)
    async with engine.begin() as connection:
        await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    yield engine
    await close_checkpointers()
    await engine.dispose()


@pytest.fixture
async def connection(engine):
    async with engine.connect() as connection:
        transaction = await connection.begin()
        yield connection
        await transaction.rollback()


def _session_on(connection) -> AsyncSession:
    return AsyncSession(
        bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )


@pytest.fixture
async def session(connection):
    async with _session_on(connection) as session:
        yield session


@pytest.fixture
def session_factory(connection):
    """Like the app's factory, but its sessions stay in the test's transaction."""

    def _factory() -> AsyncSession:
        return _session_on(connection)

    return _factory


@pytest.fixture
async def client(connection):
    async def test_session():
        # A new session per request, as in production, so nothing is cached between requests.
        async with _session_on(connection) as session:
            yield session

    app.dependency_overrides[get_session] = test_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
def make_user(session):
    async def _make_user(email="user@example.com") -> User:
        user = User(email=email, password_hash="not-a-real-hash")
        session.add(user)
        await session.commit()
        return user

    return _make_user


@pytest.fixture
def login_as(client, session):
    """Sign a user in without going through the login route, which is slow on purpose."""

    async def _login_as(user: User) -> None:
        token = new_session_token()
        session.add(
            UserSession(
                token_hash=hash_session_token(token),
                user_id=user.id,
                expires_at=utcnow() + timedelta(days=1),
            )
        )
        await session.commit()
        client.cookies.set(SESSION_COOKIE, token)

    return _login_as


@pytest.fixture
async def me(make_user, login_as) -> User:
    user = await make_user(email="me@example.com")
    await login_as(user)
    return user


@pytest.fixture
def trust_everyone(monkeypatch):
    """For tests about sharing, where new accounts would otherwise never share anything."""

    async def trusted(_repository, _user_id):
        return True

    monkeypatch.setattr(UserRepository, "is_trusted", trusted)


@pytest.fixture
def make_deck(session):
    async def _make_deck(user: User, name="Spanish 101", description=None) -> Deck:
        deck = Deck(user_id=user.id, name=name, description=description)
        session.add(deck)
        await session.commit()
        return deck

    return _make_deck


@pytest.fixture
def make_card(session):
    async def _make_card(deck: Deck, front="Question?", back="Answer", **fields) -> Card:
        card = Card(deck_id=deck.id, front=front, back=back, **fields)
        session.add(card)
        await session.commit()
        return card

    return _make_card
