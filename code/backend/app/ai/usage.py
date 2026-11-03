"""Counting what a run spends, per role, through LangChain's callbacks."""

import threading
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.embeddings import Embeddings
from langchain_core.outputs import ChatGeneration, LLMResult

from app.ai.rate_limits import ModelBusy


class RoleUsage(BaseCallbackHandler):
    """One role's spending. Failed calls count too, since they can still use up quota."""

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

    def on_llm_error(self, error: BaseException, **_: Any) -> None:
        if isinstance(error, ModelBusy):  # refused before reaching the model, so nothing was spent
            with self._lock:
                self.calls -= 1

    def on_llm_end(self, response: LLMResult, **_: Any) -> None:
        generation = response.generations[0][0] if response.generations else None
        if not isinstance(generation, ChatGeneration):
            return
        usage = getattr(generation.message, "usage_metadata", None) or {}
        with self._lock:
            self.input_tokens += usage.get("input_tokens", 0)
            self.output_tokens += usage.get("output_tokens", 0)


class CountedEmbeddings(Embeddings):
    """Counts embedding calls, because LangChain has no callbacks for embeddings."""

    def __init__(self, embeddings: Embeddings, usage: RoleUsage):
        self._embeddings = embeddings
        self._usage = usage

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self._usage.count_call()
        return self._embeddings.embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        self._usage.count_call()
        return self._embeddings.embed_query(text)

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        self._usage.count_call()
        return await self._embeddings.aembed_documents(texts)

    async def aembed_query(self, text: str) -> list[float]:
        self._usage.count_call()
        return await self._embeddings.aembed_query(text)


class RunUsage:
    """Everything one run spends, by role. A service saves it when the run ends."""

    def __init__(self) -> None:
        self._roles: dict[str, RoleUsage] = {}

    def for_role(self, role: str, model: str) -> RoleUsage:
        return self._roles.setdefault(role, RoleUsage(role, model))

    @property
    def roles(self) -> list[RoleUsage]:
        return [usage for usage in self._roles.values() if usage.calls]
