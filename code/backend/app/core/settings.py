"""Application settings, read from the environment or code/.env."""

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

EMBEDDING_DIMENSIONS = 768  # changing this means a migration and embedding everything again

_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"  # code/.env

_ASYNC_DRIVERS = {
    # Some hosts hand out postgres://, which SQLAlchemy doesn't accept.
    "postgres://": "postgresql+psycopg://",
    "postgresql://": "postgresql+psycopg://",
}


class Settings(BaseSettings):
    # Inside Docker there's no such file, and compose passes the variables in.
    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore", env_ignore_empty=True)

    database_url: str = "postgresql://postgres:postgres@postgres:5432/cadence"
    redis_url: str = "redis://valkey:6379/0"
    session_cookie_secure: bool = False  # true whenever it's served over HTTPS
    session_days: int = 30

    # "gemini" or "fake" for each role. Fake needs no key, and returns sample content.
    # Google's quotas are per model, so each role falls back to other Gemini models, in order,
    # as "vendor:model,vendor:model", once a model's daily limit is reached. A fake role has none.
    # The Flash models allow 20 calls a day each, so only the judge uses them. The writer and
    # helper share the Flash-Lite models, at 1,500 a day each, starting on different ones so the
    # load spreads.
    ai_writer_provider: str = "gemini"
    ai_writer_model: str = "gemini-3.5-flash-lite"
    ai_writer_thinking: str = "low"
    ai_writer_fallbacks: str = "gemini:gemini-3.1-flash-lite,gemini:gemini-2.5-flash-lite"
    ai_judge_provider: str = "gemini"
    ai_judge_model: str = "gemini-3.8-flash"
    ai_judge_thinking: str = "low"
    ai_judge_fallbacks: str = (
        "gemini:gemini-3.7-flash,gemini:gemini-3.6-flash,gemini:gemini-3.5-flash,"
        "gemini:gemini-3.5-flash-lite,gemini:gemini-3.1-flash-lite,gemini:gemini-2.5-flash-lite"
    )
    # The tutor chat, file screening, topic suggestions and the same-fact check.
    ai_helper_provider: str = "gemini"
    ai_helper_model: str = "gemini-3.1-flash-lite"
    ai_helper_thinking: str = "low"
    ai_helper_fallbacks: str = "gemini:gemini-3.5-flash-lite,gemini:gemini-2.5-flash-lite"
    ai_embedder_provider: str = "gemini"
    ai_embedder_model: str = "gemini-embedding-001"
    gemini_api_key: str = ""

    ai_daily_limit: int = 10  # generations per user, in a rolling 24 hours
    ai_materials_user_daily_limit: int = 10
    ai_suggestions_user_daily_limit: int = 20
    ai_tutor_enabled: bool = True
    ai_tutor_daily_limit: int = 100  # calls in 24 hours, for the whole site
    ai_tutor_user_daily_limit: int = 20  # and per learner
    ai_problem_cards_enabled: bool = True
    # Background reviews' calls in 24 hours, for the whole site and per learner, and how many calls
    # per model they must leave for learners' own requests.
    ai_problem_cards_daily_limit: int = 10
    ai_problem_cards_user_daily_limit: int = 4
    ai_problem_cards_model_reserve: int = 9
    # Calls per model in any 24 hours, as "model:limit,model:limit". Others get the default.
    # About 90% of Google's free tier, since our count is best effort.
    ai_model_daily_limit: int = 18  # the Flash models, at 20 a day
    ai_model_daily_limits: str = (
        "gemini-3.5-flash-lite:1350,gemini-3.1-flash-lite:1350,gemini-2.5-flash-lite:1350,"
        "gemini-embedding-001:900"
    )
    # Calls per model per minute across all workers, in the same form. 0 means no limit.
    ai_model_rate_limit: int = 4  # the Flash models, at 5 a minute
    ai_model_rate_limits: str = (
        "gemini-3.5-flash-lite:9,gemini-3.1-flash-lite:9,gemini-2.5-flash-lite:9,"
        "gemini-embedding-001:100"
    )

    @field_validator("database_url")
    @classmethod
    def use_an_async_driver(cls, url: str) -> str:
        for prefix, async_prefix in _ASYNC_DRIVERS.items():
            if url.startswith(prefix):
                return async_prefix + url.removeprefix(prefix)
        return url

    def model_daily_limit(self, model: str) -> int:
        limits = dict(item.strip().split(":") for item in self.ai_model_daily_limits.split(","))
        return int(limits.get(model, self.ai_model_daily_limit))

    def model_rate_limit(self, model: str) -> int:
        limits = dict(
            item.strip().split(":") for item in self.ai_model_rate_limits.split(",") if item.strip()
        )
        return int(limits.get(model, self.ai_model_rate_limit))


@lru_cache
def get_settings() -> Settings:
    """One Settings per process, so the environment is only read once."""
    return Settings()
