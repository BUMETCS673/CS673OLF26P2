"""B2: `flask ai-smoke`, the one-card check against the configured provider.

One test per acceptance example under B2 in code/plans/ITERATION_3_PLAN.md, plus the
failures around them. Every test runs on the stand-in or a patched provider (rule 16).
"""

# AI Utilization: ~100% of this file's code
# AI Tools Used: Claude Code (Claude Opus 5.5)
# AI-Assisted Activities:
#   Unit test creation (from the plan's acceptance examples)
# Human role: plan approval, code review, and hands-on testing by Miles Cameron.

import re
from unittest.mock import patch

import pytest

from app.ai.cli import ai_smoke_command
from app.ai.provider import (
    NOT_CONFIGURED,
    QUOTA_USED_UP,
    UNAVAILABLE,
    AIRateLimited,
    AIUnavailable,
    FakeProvider,
)


def _run(app):
    return app.test_cli_runner().invoke(ai_smoke_command)


class OneReply:
    """A provider that answers every call with `cards`, and records the prompt."""

    name = "gemini-test-flash"

    def __init__(self, cards):
        self.cards = cards
        self.prompts = []

    def generate_cards(self, prompt):
        self.prompts.append(prompt)
        return self.cards


def test_on_the_stand_in_it_prints_a_sample_card_and_exits_0(app):
    app.config["AI_PROVIDER"] = "fake"

    result = _run(app)

    assert result.exit_code == 0, result.output
    assert "Sample question" in result.output
    asking, answer = result.output.splitlines()
    assert asking == "Asking fake for one card. This can take up to 45 seconds…"
    assert re.fullmatch(r"fake answered in \d+\.\d s: Sample question (\d+) → Sample answer \1", answer)


def test_it_asks_for_one_card_about_the_capital_of_france(app):
    provider = OneReply([{"front": "What is the capital of France?", "back": "Paris"}])

    with patch("app.ai.cli.get_provider", return_value=provider):
        result = _run(app)

    assert result.exit_code == 0, result.output
    answer = result.output.splitlines()[-1]
    assert answer.startswith("gemini-test-flash answered in ")
    assert answer.endswith(": What is the capital of France? → Paris")
    [prompt] = provider.prompts
    assert prompt.text == "Write 1 flashcard about the capital of France."
    assert prompt.max_cards == 1
    assert prompt.attachment is None


@pytest.mark.parametrize(
    ("error", "message"),
    [(AIUnavailable, UNAVAILABLE), (AIRateLimited, QUOTA_USED_UP)],
    ids=["unavailable", "rate-limited"],
)
def test_a_provider_that_fails_prints_its_message_and_exits_1(app, error, message):
    with patch("app.ai.cli.get_provider", return_value=FakeProvider(fail_with=error)):
        result = _run(app)

    assert result.exit_code == 1
    assert message in result.output


def test_gemini_with_no_key_says_it_isnt_set_up_and_exits_1(app):
    app.config["AI_PROVIDER"] = "gemini"
    app.config["GEMINI_API_KEY"] = ""

    result = _run(app)

    assert result.exit_code == 1
    assert NOT_CONFIGURED in result.output


@pytest.mark.parametrize(
    "cards",
    [[], ["not a card"], [{"front": "What is the capital of France?"}]],
    ids=["no-cards", "not-an-object", "no-back"],
)
def test_a_reply_with_no_usable_card_exits_1(app, cards):
    with patch("app.ai.cli.get_provider", return_value=OneReply(cards)):
        result = _run(app)

    assert result.exit_code == 1
    assert "gemini-test-flash answered in " in result.output
    assert "no usable card" in result.output
