"""Metrics for model calls, and telemetry staying off without an endpoint."""

import logging

from langchain_google_genai.chat_models import GoogleAPIError

from app.ai.rate_limits import ModelBusy
from app.ai.usage import RoleUsage
from app.core.telemetry import ENDPOINT_VARIABLE, start_telemetry

JUDGE = {"role": "judge", "model": "m"}


def test_a_model_call_is_counted_by_its_outcome(metric_value):
    def calls(outcome):
        return metric_value("cadence.ai.calls", **JUDGE, outcome=outcome)

    before = {outcome: calls(outcome) for outcome in ("ok", "busy", "overloaded")}
    usage = RoleUsage("judge", "m")

    usage.record_success(10, 5)
    usage.on_llm_error(ModelBusy())
    usage.on_llm_error(GoogleAPIError(503, {"error": {"code": 503, "message": "x", "status": "X"}}))

    assert {outcome: calls(outcome) - before[outcome] for outcome in before} == {
        "ok": 1,
        "busy": 1,
        "overloaded": 1,
    }


def test_tokens_are_counted_by_direction(metric_value):
    def tokens(direction):
        return metric_value("cadence.ai.tokens", **JUDGE, direction=direction)

    before = (tokens("input"), tokens("output"))

    RoleUsage("judge", "m").record_success(10, 5)

    assert (tokens("input") - before[0], tokens("output") - before[1]) == (10, 5)


def test_without_an_endpoint_nothing_is_sent(monkeypatch):
    monkeypatch.delenv(ENDPOINT_VARIABLE, raising=False)
    handlers = logging.getLogger().handlers[:]

    stop = start_telemetry("api")
    stop()

    assert logging.getLogger().handlers == handlers
