"""Stand-in models, for tests and for running the app without an API key."""

import itertools
import random
from collections.abc import Sequence
from typing import Any

from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool

from app.core.settings import EMBEDDING_DIMENSIONS

_DEFAULT_LIST_LENGTH = 25  # callers trim to what they asked for
_LABELS = {"front": "Sample question", "back": "Sample answer"}

# One counter for the whole process, so a second batch never repeats the first one's cards.
_sample_numbers = itertools.count(1)


def _fill(schema: dict, key: str = "", position: int = 0) -> Any:
    """A valid value for a JSON schema. Fields of one object share a number, so they pair up."""
    return _fill_numbered(schema, key, position, next(_sample_numbers))


def _fill_numbered(schema: dict, key: str, position: int, number: int) -> Any:
    if "enum" in schema:
        return schema["enum"][0]
    kind = schema.get("type")
    if kind == "object":
        return {
            name: _fill_numbered(field, name, position, number)
            for name, field in schema.get("properties", {}).items()
        }
    if kind == "array":
        length = schema.get("maxItems", _DEFAULT_LIST_LENGTH)
        return [_fill(schema["items"], key, index) for index in range(length)]
    if kind == "integer":
        return position
    if kind == "boolean":
        return True
    return f"{_LABELS.get(key, f'Sample {key}')} {number}"


def _chosen_tool(tools: Sequence[Any], tool_choice: Any) -> dict:
    """The named tool if one is required, otherwise the last, which callers make the final step."""
    converted = [convert_to_openai_tool(tool)["function"] for tool in tools]
    for tool in converted:
        if tool["name"] == tool_choice:
            return tool
    return converted[-1]


class FakeChatModel(BaseChatModel):
    """Answers any tool or schema by filling it in. Supports `with_structured_output`."""

    @property
    def _llm_type(self) -> str:
        return "fake"

    def bind_tools(self, tools: Sequence[Any], *, tool_choice: Any = None, **_: Any):
        return self.bind(tools=tools, tool_choice=tool_choice)

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        tools: Sequence[Any] | None = None,
        tool_choice: Any = None,
        **_: Any,
    ) -> ChatResult:
        usage = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
        if tools:
            tool = _chosen_tool(tools, tool_choice)
            call = {
                "name": tool["name"],
                "args": _fill(tool["parameters"]),
                "id": "fake-call",
                "type": "tool_call",
            }
            message = AIMessage(content="", tool_calls=[call], usage_metadata=usage)
        else:
            message = AIMessage(content="A sample reply.", usage_metadata=usage)
        return ChatResult(generations=[ChatGeneration(message=message)])


class FakeEmbeddings(Embeddings):
    """Seeded by the text, so the same text always gets the same vector."""

    def _vector(self, text: str) -> list[float]:
        numbers = random.Random(text)
        return [numbers.random() for _ in range(EMBEDDING_DIMENSIONS)]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)
