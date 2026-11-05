"""Counting what a run spends, per role, through LangChain's callbacks."""

import logging
import threading
import time
from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import ChatGeneration, LLMResult

from app.ai.failures import classify
from app.core.telemetry import meter

logger = logging.getLogger(__name__)

AI_CALLS = meter.create_counter(
    "cadence.ai.calls", unit="{call}", description="Model calls, by role, model and outcome."
)
AI_TOKENS = meter.create_counter(
    "cadence.ai.tokens", unit="{token}", description="Tokens, by role, model and direction."
)


class RoleUsage(BaseCallbackHandler):
    """One role's spending, under the model that ran each call, and the metrics for each call.

    A failed call still counts, since a timeout can come after the model did the work. A call
    that was refused doesn't, so a fallback doesn't charge the model that turned it away.
    """

    def __init__(self, role: str, model: str):
        self.role = role
        self.model = model  # one handler per model so a fallback is charged to its own model
        self.calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self._lock = threading.Lock()  # parallel calls can finish together
        self._started: dict[UUID, float] = {}  # each call's start by LangChain's run ID

    def count_call(self) -> None:
        with self._lock:  # += isn't atomic across threads
            self.calls += 1

    def on_chat_model_start(self, *_: Any, run_id: UUID | None = None, **__: Any) -> None:
        # Step 1: count the call up front since a timeout can come after the model worked
        self.count_call()
        # Step 2: note when it started to log its duration when it ends
        if run_id is not None:  # run_id ties this start to its end callback
            # monotonic so clock changes don't affect it
            self._started[run_id] = time.perf_counter()
        logger.info("ai call started", extra=self._labels())

    def _log_end(self, run_id: UUID | None, outcome: str, **counts: int) -> None:
        """Logs the call's outcome, with how long it took when its start was seen."""
        fields: dict[str, str | int | float] = {**self._labels(outcome=outcome), **counts}
        # pop so the dict doesn't grow with every call
        started = self._started.pop(run_id, None) if run_id is not None else None
        if started is not None:  # left out instead of None since OpenTelemetry drops None fields
            fields["seconds"] = round(time.perf_counter() - started, 3)
        logger.info("ai call ended", extra=fields)

    def refund_call(self) -> None:
        with self._lock:
            self.calls -= 1

    def record_success(self, input_tokens: int = 0, output_tokens: int = 0) -> None:
        # Step 1: add the tokens to this role's spending
        with self._lock:
            self.input_tokens += input_tokens
            self.output_tokens += output_tokens
        # Step 2: count the call and its tokens in the OpenTelemetry metrics for Grafana
        AI_CALLS.add(1, self._labels(outcome="ok"))
        AI_TOKENS.add(input_tokens, self._labels(direction="input"))
        AI_TOKENS.add(output_tokens, self._labels(direction="output"))

    def record_error(self, error: BaseException) -> None:
        """Counts the failure by its kind, and refunds the call if it was refused."""
        # Step 1: name the failure such as busy, rate_limited, overloaded or permanent
        failure = classify(error)
        AI_CALLS.add(1, self._labels(outcome=failure.value if failure else "error"))
        # Step 2: a refused call never ran so it shouldn't use up the model's daily budget
        if failure is not None and failure.refused:  # busy, rate_limited or overloaded
            self.refund_call()

    def _labels(self, **more: str) -> dict[str, str]:
        return {"role": str(self.role), "model": self.model, **more}  # metric and log labels

    def on_llm_error(self, error: BaseException, *, run_id: UUID | None = None, **_: Any) -> None:
        self.record_error(error)  # LangChain calls this before the fallback tries the next model
        self._log_end(run_id, "error")

    def on_llm_end(self, response: LLMResult, *, run_id: UUID | None = None, **_: Any) -> None:
        # Step 1: read the token counts the model reported if any
        generation = response.generations[0][0] if response.generations else None
        usage = {}
        if isinstance(generation, ChatGeneration):  # chat replies carry usage_metadata
            # None when the model reports no usage
            usage = getattr(generation.message, "usage_metadata", None) or {}
        input_tokens, output_tokens = usage.get("input_tokens", 0), usage.get("output_tokens", 0)

        # Step 2: add them to this role's spending and to the metrics
        self.record_success(input_tokens, output_tokens)
        self._log_end(run_id, "ok", input_tokens=input_tokens, output_tokens=output_tokens)


class RunUsage:
    """Everything one run spends, by role and model. A service saves it when the run ends."""

    def __init__(self) -> None:
        # By model too, since a role's fallback is a different model with its own budget.
        self._roles: dict[tuple[str, str], RoleUsage] = {}

    def for_role(self, role: str, model: str) -> RoleUsage:
        # setdefault makes one handler per (role, model) on first use
        return self._roles.setdefault((role, model), RoleUsage(role, model))

    @property
    def roles(self) -> list[RoleUsage]:
        # only those that made a call so a model that was never tried gets no usage row
        return [usage for usage in self._roles.values() if usage.calls]
