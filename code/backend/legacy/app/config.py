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


RENAMED_SETTINGS = {
    "AI_PROVIDER": "AI_WRITER_PROVIDER and AI_JUDGE_PROVIDER",
    "GEMINI_MODEL": "AI_WRITER_MODEL",
    "AI_SITE_DAILY_LIMIT": "AI_MODEL_DAILY_LIMIT",
    "AI_LEECH_SITE_RESERVE": "AI_LEECH_MODEL_RESERVE",
}


def renamed_settings_in_use() -> dict[str, str]:
    """Old setting names still in the environment, which the app ignores, and their new names."""
    return {old: new for old, new in RENAMED_SETTINGS.items() if _env(old, "")}


def _model_limits(text: str) -> dict[str, int]:
    """Parse "model:limit,model:limit". A malformed value stops the app from starting."""
    limits = {}
    for item in (part.strip() for part in text.split(",")):
        if item:
            model, separator, limit = item.partition(":")
            if not separator:
                raise ValueError(f"AI_MODEL_DAILY_LIMITS needs model:limit, got {item!r}")
            limits[model.strip()] = int(limit)
    return limits


class Config:
    # Signs the session cookie. The fallback only exists so `docker compose up` works
    # out of the box; anything deployed anywhere must set this in the environment.
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")

    SQLALCHEMY_DATABASE_URI = _database_url()
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Security basics.
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
    # Vendor and model per role. Vendors are registered in app/ai/provider.py.
    AI_WRITER_PROVIDER = _env("AI_WRITER_PROVIDER", "gemini")  # or "fake": sample cards, no Google
    AI_WRITER_MODEL = _env("AI_WRITER_MODEL", "gemini-3.5-flash-lite")
    AI_JUDGE_PROVIDER = _env("AI_JUDGE_PROVIDER", "gemini")
    AI_JUDGE_MODEL = _env("AI_JUDGE_MODEL", "gemini-3.8-flash")
    AI_EMBEDDER_PROVIDER = _env("AI_EMBEDDER_PROVIDER", "gemini")
    # Not gemini-embedding-2, which merges a list of inputs into one vector.
    AI_EMBEDDER_MODEL = _env("AI_EMBEDDER_MODEL", "gemini-embedding-001")
    # How hard each role's model thinks. Higher is slower, and every call has a 45 s timeout.
    AI_WRITER_THINKING = _env("AI_WRITER_THINKING", "low")
    AI_JUDGE_THINKING = _env("AI_JUDGE_THINKING", "low")
    GEMINI_API_KEY = _env("GEMINI_API_KEY", "")  # secret: the environment only
    AI_DAILY_LIMIT = int(_env("AI_DAILY_LIMIT", "10"))  # generations per user, rolling 24 h
    # Calls per model across all features, rolling 24 h, as "model:limit,model:limit". Unlisted
    # models get AI_MODEL_DAILY_LIMIT. Google's free quota is per project and per model, and its
    # docs no longer publish the numbers. The defaults sit under third-party figures of 500 and
    # 20 a day, so confirm them in AI Studio.
    AI_MODEL_DAILY_LIMIT = int(_env("AI_MODEL_DAILY_LIMIT", "18"))
    AI_MODEL_DAILY_LIMITS = _model_limits(
        _env(
            "AI_MODEL_DAILY_LIMITS",
            "gemini-3.5-flash-lite:450,gemini-3.8-flash:18,gemini-embedding-001:900",
        )
    )
    AI_MAX_CARDS = 25  # cards per generate request
    # Set to "false" to stop the background jobs. Pending suggestions can still be reviewed.
    AI_LEECH_ENABLED = _env("AI_LEECH_ENABLED", "true").lower() != "false"
    # Leech Doctor calls, rolling 24 h: site-wide and per learner.
    AI_LEECH_DAILY_LIMIT = int(_env("AI_LEECH_DAILY_LIMIT", "10"))
    AI_LEECH_USER_DAILY_LIMIT = int(_env("AI_LEECH_USER_DAILY_LIMIT", "4"))
    # Calls per model that background jobs leave for learners' own requests.
    AI_LEECH_MODEL_RESERVE = int(_env("AI_LEECH_MODEL_RESERVE", "9"))
    AI_LEECH_RUN_INLINE = False  # tests run jobs in the request instead of a thread
    AI_SUGGESTIONS_USER_DAILY_LIMIT = int(_env("AI_SUGGESTIONS_USER_DAILY_LIMIT", "20"))
    AI_MATERIALS_RUN_INLINE = False  # likewise
    AI_MATERIALS_USER_DAILY_LIMIT = int(_env("AI_MATERIALS_USER_DAILY_LIMIT", "10"))  # new files
    # Set to "false" to turn off the tutor. Its calls, rolling 24 h: site-wide and per learner.
    AI_TUTOR_ENABLED = _env("AI_TUTOR_ENABLED", "true").lower() != "false"
    AI_TUTOR_DAILY_LIMIT = int(_env("AI_TUTOR_DAILY_LIMIT", "100"))
    AI_TUTOR_USER_DAILY_LIMIT = int(_env("AI_TUTOR_USER_DAILY_LIMIT", "20"))


class TestConfig(Config):
    """Used by `tests/conftest.py`. Keeps tests off the real database, and off Google."""

    TESTING = True
    SQLALCHEMY_DATABASE_URI = os.environ.get("TEST_DATABASE_URL", "sqlite://")
    SECRET_KEY = "test-secret"
    WTF_CSRF_ENABLED = False

    # Rule 16: no test touches the network. The key is blanked too, so a real one in
    # someone's code/.env can't reach a test that switches AI_PROVIDER to "gemini". The
    # limits are pinned so a value left in .env can't change what the cap tests count to.
    AI_WRITER_PROVIDER = "fake"
    AI_JUDGE_PROVIDER = "fake"
    AI_EMBEDDER_PROVIDER = "fake"
    AI_LEECH_ENABLED = True
    AI_LEECH_DAILY_LIMIT = 10
    AI_LEECH_USER_DAILY_LIMIT = 4
    AI_LEECH_MODEL_RESERVE = 9
    AI_LEECH_RUN_INLINE = True
    AI_SUGGESTIONS_USER_DAILY_LIMIT = 20
    AI_MATERIALS_RUN_INLINE = True
    AI_MATERIALS_USER_DAILY_LIMIT = 10
    AI_TUTOR_ENABLED = True
    AI_TUTOR_DAILY_LIMIT = 100
    AI_TUTOR_USER_DAILY_LIMIT = 20
    GEMINI_API_KEY = ""
    AI_DAILY_LIMIT = 10
    AI_MODEL_DAILY_LIMIT = 18
    AI_MODEL_DAILY_LIMITS = {}
