"""The stand-in provider: tests, development without a key, and the demo fallback (A3).

It answers any feature's schema without knowing the feature, by filling the schema in.
"""

import itertools
import json

from app.ai.provider import Prompt, Provider

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


class FakeProvider(Provider):
    def __init__(self, fail_with: type[Exception] | None = None):
        super().__init__("fake")
        self.fail_with = fail_with

    def _complete(self, prompt: Prompt, schema: dict) -> str:
        if self.fail_with is not None:
            raise self.fail_with()
        return json.dumps(_fill(schema, "", 0, next(_sample_numbers)))
