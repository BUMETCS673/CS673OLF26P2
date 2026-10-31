"""The stand-in provider: tests, development without a key, and the demo fallback (A3)."""

import itertools
import json

from app.ai.provider import Prompt, Provider

# One counter for the whole process, so a second batch never repeats the first one's
# fronts. If it did, cleanup would drop them as copies of cards already accepted.
_sample_numbers = itertools.count(1)


class FakeProvider(Provider):
    def __init__(self, fail_with: type[Exception] | None = None):
        super().__init__("fake")
        self.fail_with = fail_with

    def _complete(self, prompt: Prompt, schema: dict) -> str:
        if self.fail_with is not None:
            raise self.fail_with()
        # Each schema has one required key, which identifies the kind of reply.
        key = schema["required"][0]
        if key == "cards":
            numbers = [next(_sample_numbers) for _ in range(prompt.max_cards)]
            items = [
                {"front": f"Sample question {n}", "back": f"Sample answer {n}"} for n in numbers
            ]
        elif key == "verdicts":
            # Approve every candidate. In a judge prompt, max_cards is the candidate count.
            items = [{"index": index, "ok": True} for index in range(prompt.max_cards)]
        elif key == "recommendations":
            # In a Leech Doctor prompt, max_cards is the number of cards.
            items = [
                {
                    "index": index,
                    "options": [{
                        "kind": "rewrite",
                        "reason": "Sample reason.",
                        "cards": [{
                            "front": f"Sample question {(n := next(_sample_numbers))}",
                            "back": f"Sample answer {n}",
                        }],
                    }],
                }
                for index in range(prompt.max_cards)
            ]
            return json.dumps({"shared_cause": "Sample shared cause.", key: items})
        else:
            items = [f"Sample fact {next(_sample_numbers)}"]
        return json.dumps({key: items})
