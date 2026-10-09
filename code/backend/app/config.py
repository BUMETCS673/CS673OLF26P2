"""Application settings, read from the environment.

Nothing secret is written down here. `SECRET_KEY`, `DATABASE_URL` and `GEMINI_API_KEY`
come from the environment (docker-compose passes them in; see `code/.env.example`).
"""

# Iteration 3, Step 0a: _env() and the AI settings.
# AI Utilization: ~100% of that change
# AI Tools Used: Claude Code (Claude Opus 5.5)
# AI-Assisted Activities:
#   Configuration
# Human role: plan approval, code review, and hands-on testing by Miles Cameron.

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


def _env(name: str, default: str) -> str:
    """The environment variable `name`, or `default` when it's unset or blank.

    docker-compose passes `${GEMINI_MODEL:-}` through as an empty string when .env
    doesn't set it. Read with a plain `os.environ.get(name, default)`, that empty string
    is "present", and it would replace the default rather than fall back to it.
    """
    return (os.environ.get(name) or "").strip() or default


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

    # Cap on a request body, so nobody can make us buffer an arbitrarily large one.
    # Deliberately generous: a card is at most 2000 characters a side, so real requests
    # are a few KB. The slack means someone pasting something huge still gets the 422
    # naming the field, rather than a blunt "too large" on a legitimate mistake.
    MAX_CONTENT_LENGTH = 1024 * 1024  # 1 MB

    # AI card generation (Iteration 3). Nothing reads these at startup, so the app boots
    # without a key; generating answers 503 until one is set. See app/ai/provider.py.
    AI_PROVIDER = _env("AI_PROVIDER", "gemini")  # or "fake": sample cards, no Google
    GEMINI_API_KEY = _env("GEMINI_API_KEY", "")  # secret: the environment only
    GEMINI_MODEL = _env("GEMINI_MODEL", "gemini-3.5-flash")
    AI_DAILY_LIMIT = int(_env("AI_DAILY_LIMIT", "10"))  # generations per user, rolling 24 h
    AI_MAX_CARDS = 25  # cards per generate request


class TestConfig(Config):
    """Used by `tests/conftest.py`. Keeps tests off the real database, and off Google."""

    TESTING = True
    SQLALCHEMY_DATABASE_URI = os.environ.get("TEST_DATABASE_URL", "sqlite://")
    SECRET_KEY = "test-secret"
    WTF_CSRF_ENABLED = False

    # Rule 16: no test touches the network. The key is blanked too, so a real one in
    # someone's code/.env can't reach a test that switches AI_PROVIDER to "gemini". The
    # limit is pinned so a value left in .env can't change what the cap tests count to.
    AI_PROVIDER = "fake"
    GEMINI_API_KEY = ""
    AI_DAILY_LIMIT = 10
