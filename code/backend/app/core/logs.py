"""Logging for the API and the worker: one line per event on stdout, as JSON by default.

Each line carries the request or job it belongs to, so a log tool can follow one request across
lines. Lines never carry what a learner wrote or uploaded: log types, counts and IDs only.
"""

import logging
import logging.config
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from pythonjsonlogger.json import JsonFormatter

from app.core.settings import Settings

# Loggers that set up their own handlers. Theirs go through ours, so every line has one format.
_OTHER_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access", "taskiq")

_fields: ContextVar[Mapping[str, Any] | None] = ContextVar("log_fields", default=None)


@contextmanager
def log_fields(**fields: Any) -> Iterator[None]:
    """Adds `fields` to every line logged inside, in tasks started inside too."""
    token = _fields.set({**(_fields.get() or {}), **fields})
    try:
        yield
    finally:
        _fields.reset(token)


def add_log_fields(**fields: Any) -> None:
    """Adds `fields` until the surrounding `log_fields` ends."""
    _fields.set({**(_fields.get() or {}), **fields})


class FieldsFilter(logging.Filter):
    """Puts the current fields on each record a handler writes.

    On the handler rather than in a record factory, so it runs after `extra`, and a call that
    passes a field of the same name keeps its own value instead of failing.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        for key, value in (_fields.get() or {}).items():
            if not hasattr(record, key):
                setattr(record, key, value)
        return True


def _formatter(log_format: str) -> dict[str, Any]:
    if log_format == "text":
        return {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}
    return {
        "()": JsonFormatter,
        "fmt": "%(levelname)s %(name)s %(message)s",
        "rename_fields": {"levelname": "level", "name": "logger"},
        "timestamp": "time",
    }


def configure_logging(settings: Settings) -> None:
    """Sends every logger to stdout in one format. Call it once as a process starts."""
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {"default": _formatter(settings.log_format)},
            "filters": {"fields": {"()": FieldsFilter}},
            "handlers": {
                "stdout": {
                    "class": "logging.StreamHandler",
                    "stream": "ext://sys.stdout",
                    "formatter": "default",
                    "filters": ["fields"],
                }
            },
            "root": {"level": settings.log_level.upper(), "handlers": ["stdout"]},
            "loggers": {name: {"handlers": [], "propagate": True} for name in _OTHER_LOGGERS},
        }
    )
