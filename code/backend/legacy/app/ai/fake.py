"""The stand-in provider: tests, development without a key, and the demo fallback (A3).

It answers any feature's schema without knowing the feature, by filling the schema in.
"""

import itertools
import json
import random
from collections.abc import Sequence

from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool

from app.ai.provider import EMBEDDING_DIMENSIONS, Prompt, Provider

# One counter for the whole process, so a second batch never repeats the first one's
# fronts. If it did, cleanup would drop them as copies of cards already accepted.
_sample_numbers = itertools.count(1)

_LABELS = {"front": "Sample question", "back": "Sample answer"}


def _fill(schema: dict, key: str, position: int, number: int):
    """A valid value for `schema`. Fields of one object share a number, so they read as a pair."""
    if "enum" in schema:
        return schema["enum"][0]
    kind = schema.get("type")
    if kind == "object":
        return {
            name: _fill(field, name, position, number)
            for name, field in schema.get("properties", {}).items()
        }
    if kind == "array":
        return [
            _fill(schema["items"], key, index, next(_sample_numbers))
            for index in range(schema.get("maxItems", 1))
        ]
    if kind == "integer":
        return position
    if kind == "boolean":
        return True
    return f"{_LABELS.get(key, f'Sample {key}')} {number}"


def _vector(text: str) -> list[float]:
    """Seeded by the text, so the same text always gets the same vector."""
    numbers = random.Random(text)
    return [numbers.random() for _ in range(EMBEDDING_DIMENSIONS)]


class FakeProvider(Provider):
    def __init__(self, fail_with: type[Exception] | None = None):
        super().__init__("fake")
        self.fail_with = fail_with

    def _complete(self, prompt: Prompt, schema: dict) -> str:
        if self.fail_with is not None:
            raise self.fail_with()
        return json.dumps(_fill(schema, "", 0, next(_sample_numbers)))

    def _chat(
        self, messages: Sequence[BaseMessage], tools: Sequence[BaseTool], tool_choice: str | None
    ) -> AIMessage:
        """Calls `tool_choice` if given, otherwise the last tool, with arguments from its schema.

        Callers list a tool that finishes the job last, so a run with this provider ends.
        """
        if self.fail_with is not None:
            raise self.fail_with()
        tool = next((tool for tool in tools if tool.name == tool_choice), tools[-1])
        schema = convert_to_openai_tool(tool)["function"]["parameters"]
        call = {
            "name": tool.name,
            "args": _fill(schema, "", 0, next(_sample_numbers)),
            "id": "fake-call",
            "type": "tool_call",
        }
        return AIMessage(content="", tool_calls=[call])

    def _embed(self, texts: list[str], is_query: bool) -> list[list[float]]:
        if self.fail_with is not None:
            raise self.fail_with()
        return [_vector(text) for text in texts]
