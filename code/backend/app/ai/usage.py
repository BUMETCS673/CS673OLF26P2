"""Counting what a run spends, per role, through LangChain's callbacks."""

import threading
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import ChatGeneration, LLMResult

from app.ai.failures import classify


def was_refused(error: BaseException) -> bool:
    """Whether the call was turned away before the model ran it, so it spent nothing."""
    failure = classify(error)
    return failure is not None and failure.refused


class RoleUsage(BaseCallbackHandler):
    """One role's spending, under the model that ran each call.

    A failed call still counts, since a timeout can come after the model did the work. A call
    that was refused doesn't, so a fallback doesn't charge the model that turned it away.
    """

    def __init__(self, role: str, model: str):
        self.role = role
        self.model = model
        self.calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self._lock = threading.Lock()  # parallel calls can finish together

    def count_call(self) -> None:
        with self._lock:
            self.calls += 1

    def on_chat_model_start(self, *_: Any, **__: Any) -> None:
        self.count_call()

    def refund_call(self) -> None:
        with self._lock:
            self.calls -= 1

    def on_llm_error(self, error: BaseException, **_: Any) -> None:
        if was_refused(error):
            self.refund_call()

    def on_llm_end(self, response: LLMResult, **_: Any) -> None:
        generation = response.generations[0][0] if response.generations else None
        if not isinstance(generation, ChatGeneration):
            return
        usage = getattr(generation.message, "usage_metadata", None) or {}
        with self._lock:
            self.input_tokens += usage.get("input_tokens", 0)
            self.output_tokens += usage.get("output_tokens", 0)


class RunUsage:
    """Everything one run spends, by role and model. A service saves it when the run ends."""

    def __init__(self) -> None:
        # By model too, since a role's fallback is a different model with its own budget.
        self._roles: dict[tuple[str, str], RoleUsage] = {}

    def for_role(self, role: str, model: str) -> RoleUsage:
        return self._roles.setdefault((role, model), RoleUsage(role, model))

    @property
    def roles(self) -> list[RoleUsage]:
        return [usage for usage in self._roles.values() if usage.calls]
