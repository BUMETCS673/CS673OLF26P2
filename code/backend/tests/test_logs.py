"""Log format, and the fields each line carries."""

import json
import logging

import pytest

from app.core.logs import add_log_fields, configure_logging, log_fields
from app.core.settings import Settings

logger = logging.getLogger("app.test")


@pytest.fixture
def restore_logging():
    """configure_logging changes the whole process, so each test puts it back."""
    names = ["", "uvicorn", "uvicorn.error", "uvicorn.access", "taskiq"]
    saved = {
        name: (logging.getLogger(name).handlers[:], logging.getLogger(name).level)
        for name in names
    }
    yield
    for name, (handlers, level) in saved.items():
        logging.getLogger(name).handlers = handlers
        logging.getLogger(name).setLevel(level)


# --- format -------------------------------------------------------------------------------


def test_a_json_line_has_the_level_logger_message_and_fields(restore_logging, capsys):
    configure_logging(Settings(log_format="json"))

    with log_fields(request_id="abc"):
        logger.warning("ai call failed", extra={"status": 503})

    line = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert line["level"] == "WARNING"
    assert line["logger"] == "app.test"
    assert line["message"] == "ai call failed"
    assert (line["request_id"], line["status"]) == ("abc", 503)
    assert "time" in line


def test_a_text_line_is_for_reading(restore_logging, capsys):
    configure_logging(Settings(log_format="text"))

    logger.info("hello")

    assert capsys.readouterr().out.strip().endswith("INFO app.test hello")


def test_the_level_setting_drops_quieter_lines(restore_logging, capsys):
    configure_logging(Settings(log_format="text", log_level="warning"))

    logger.info("quiet")
    logger.warning("loud")

    out = capsys.readouterr().out
    assert "quiet" not in out
    assert "loud" in out


# --- fields -------------------------------------------------------------------------------


def test_fields_last_until_their_block_ends(logged):
    with log_fields(job_id=1):
        add_log_fields(kind="echo")
        logger.info("inside")
    logger.info("after")

    inside, after = [record for record in logged.records if record.name == "app.test"]
    assert (inside.job_id, inside.kind) == (1, "echo")
    assert not hasattr(after, "job_id")
    assert not hasattr(after, "kind")


def test_a_lines_own_value_wins_over_a_field(logged):
    with log_fields(status="from the block"):
        logger.info("line", extra={"status": "its own"})

    [line] = [record for record in logged.records if record.name == "app.test"]
    assert line.status == "its own"
