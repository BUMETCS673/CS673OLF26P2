"""Application settings, read from the environment.

Nothing secret is written down here. `SECRET_KEY` and `DATABASE_URL` come from the
environment (docker-compose passes them in; see `code/.env.example`).
"""

import os

from dotenv import load_dotenv

# Must run before anything below reads the environment. Inside Docker there's no .env
# (compose passes the variables in); outside it, this picks up code/.env.
load_dotenv()


def _database_url() -> str:
    """The SQLAlchemy connection string.

    Some hosts hand out URLs starting with `postgres://`, which SQLAlchemy dropped
    support for. Normalize it so either spelling works.
    """
    url = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@postgres:5432/cadence")
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


class Config:
    # Signs the session cookie. The fallback only exists so `docker compose up` works
    # out of the box; anything deployed anywhere must set this in the environment.
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")

    SQLALCHEMY_DATABASE_URI = _database_url()
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Security basics, item 4 in the plan.
    SESSION_COOKIE_HTTPONLY = True   # page scripts can't read the session cookie
    SESSION_COOKIE_SAMESITE = "Lax"  # other sites can't make requests as you
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "0") == "1"

    JSON_SORT_KEYS = False


class TestConfig(Config):
    """Used by `tests/conftest.py`. Keeps tests off the real database."""

    TESTING = True
    SQLALCHEMY_DATABASE_URI = os.environ.get("TEST_DATABASE_URL", "sqlite://")
    SECRET_KEY = "test-secret"
    WTF_CSRF_ENABLED = False
