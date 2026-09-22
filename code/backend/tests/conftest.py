"""Shared pytest fixtures. WS1 and WS2 build their tests on these.

Tests run against an in-memory SQLite database, so `pytest` works without Docker and
each test starts from empty tables. Point TEST_DATABASE_URL at Postgres to run the same
suite against the real thing.

    cd code/backend
    pip install -r requirements.txt
    pytest

What you get:

    def test_something(client, make_user, login_as):
        user = make_user(email="a@example.com", password="password123")
        login_as(user)
        assert client.get("/api/decks").status_code != 401
"""

import os
import sqlite3
import sys

import pytest
from sqlalchemy import event
from sqlalchemy.engine import Engine

# So `import app` works when pytest is run from code/backend.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402
from app.config import TestConfig  # noqa: E402
from app.extensions import db as _db  # noqa: E402
from app.models import Card, Deck, User  # noqa: E402


@event.listens_for(Engine, "connect")
def _enforce_sqlite_foreign_keys(dbapi_connection, connection_record):
    """SQLite ignores foreign keys unless you ask it not to.

    Without this, "deleting a deck deletes its cards" would pass in Postgres and
    quietly do nothing in the tests.
    """
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


@pytest.fixture
def app():
    app = create_app(TestConfig)
    with app.app_context():
        _db.create_all()
        yield app
        _db.session.remove()
        _db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def db(app):
    return _db


@pytest.fixture
def make_user(db):
    """Create a user directly, without going through the register endpoint."""

    def _make_user(email="user@example.com", password="password123", display_name=None):
        # Deliberately passes the email through as given: the model normalizes it, and
        # a fixture that did it here would hide a model that stopped doing its job.
        user = User(email=email, display_name=display_name)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return user

    return _make_user


@pytest.fixture
def login_as(client):
    """Sign a user in without needing WS1's login endpoint.

    Sets the session key Flask-Login reads, which is what a real login ends up doing.
    """

    def _login_as(user):
        with client.session_transaction() as session:
            session["_user_id"] = str(user.id)
            session["_fresh"] = True

    return _login_as


@pytest.fixture
def make_deck(db):
    def _make_deck(user, name="Spanish 101", description=None, cards=()):
        deck = Deck(
            user=user,
            name=name,
            description=description,
            cards=[Card(front=front, back=back) for front, back in cards],
        )
        db.session.add(deck)
        db.session.commit()
        return deck

    return _make_deck
