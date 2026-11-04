"""Application settings, read from the environment or code/.env."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

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
    log_level: str = "INFO"
    log_format: Literal["json", "text"] = "json"  # text is easier to read in a terminal

    # "gemini" or "fake" for each role. Fake needs no key, and returns sample content.
    # Google's quotas are per model, so each role falls back to other models, in order, as
    # "vendor:model,vendor:model", once a model's daily limit is reached. A fake role has none.
    # Gemma 4 runs on the same Gemini key. Free-tier calls a day: Flash 20, 3.5 and
    # 3.1 Flash-Lite 1,500, Gemma 4 14,400.
    #
    # The judge's chain is also the strength order, strongest first, and ranks every writer and
    # helper model, so the judge always checks a weaker model's cards. From published results:
    # 3.5 Flash-Lite often beats 3 Flash (Google's own figures), Gemma 4 31B scores close to
    # 3.1 Flash-Lite but states more wrong facts, Gemma 4 26B is a step below 31B.
    #
    # The writer starts on the Flash-Lites. The helper makes the most calls, so it starts on Gemma,
    # which leaves the Flash-Lites to the writer, and stops at 3.1 Flash-Lite, so the tutor's judge
    # can still use 3.5 Flash-Lite and 3 Flash. When no judge above the writer has room, the run
    # moves the writer down its chain, which opens more judges to it, rather than refusing.
    ai_writer_provider: str = "gemini"
    ai_writer_model: str = "gemini-3.5-flash-lite"
    ai_writer_thinking: str = "low"
    ai_writer_fallbacks: str = (
        "gemini:gemini-3.1-flash-lite,gemini:gemma-4-31b-it,gemini:gemma-4-26b-a4b-it"
    )
    ai_judge_provider: str = "gemini"
    ai_judge_model: str = "gemini-3.8-flash"
    ai_judge_thinking: str = "low"
    ai_judge_fallbacks: str = (
        "gemini:gemini-3.7-flash,gemini:gemini-3.6-flash,gemini:gemini-3.5-flash,"
        "gemini:gemini-3.5-flash-lite,gemini:gemini-3-flash-preview,gemini:gemini-3.1-flash-lite,"
        "gemini:gemma-4-31b-it,gemini:gemma-4-26b-a4b-it"
    )
    # The tutor chat, file screening, topic suggestions and the same-fact check.
    ai_helper_provider: str = "gemini"
    ai_helper_model: str = "gemma-4-31b-it"
    ai_helper_thinking: str = "low"  # Gemini 3 only, so the Gemma models don't get it
    ai_helper_fallbacks: str = (
        "gemini:gemma-4-26b-a4b-it,gemini:gemini-3.1-flash-lite"
    )
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
        "gemini-3.5-flash-lite:1350,gemini-3.1-flash-lite:1350,"
        "gemma-4-31b-it:12960,gemma-4-26b-a4b-it:12960,gemini-embedding-001:900"
    )
    # Calls per model per minute across all workers, in the same form. 0 means no limit.
    ai_model_rate_limit: int = 4  # the Flash models, at 5 a minute
    # Gemma 4's own limits aren't published. These assume Gemma 3's 30 a minute. A call over its
    # tokens-a-minute cap gets a 429, which falls back to the next model and isn't charged.
    ai_model_rate_limits: str = (
        "gemini-3.5-flash-lite:9,gemini-3.1-flash-lite:9,"
        "gemma-4-31b-it:27,gemma-4-26b-a4b-it:27,gemini-embedding-001:100"
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
