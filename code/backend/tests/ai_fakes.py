"""Test doubles for `Provider`, and helpers for the usage table."""

from datetime import timedelta
from types import SimpleNamespace

from sqlalchemy import func, select

from app.extensions import db
from app.models import AiUsage, utcnow


def spend(user_id, calls, feature="generate", model="fake", hours_ago=0):
    """Save `calls` as already spent."""
    db.session.add(AiUsage(
        feature=feature, role="writer", model=model, user_id=user_id, calls=calls,
        input_tokens=0, output_tokens=0, created_at=utcnow() - timedelta(hours=hours_ago),
    ))
    db.session.commit()


def calls_used(feature):
    """Every call saved for `feature`."""
    return db.session.scalar(
        select(func.coalesce(func.sum(AiUsage.calls), 0)).where(AiUsage.feature == feature)
    )


class Scripted:
    """Answers each call with the next reply, or raises it if it is an exception.

    A list is wrapped under the schema's required key, so a test can script just the items.
    """

    name = "scripted"

    def __init__(self, *replies):
        self.replies = list(replies)
        self.prompts = []
        self.schemas = []
        self.usage = SimpleNamespace(input_tokens=10, output_tokens=5, calls=0)

    def complete_json(self, prompt, schema):
        self.usage.calls += 1
        self.prompts.append(prompt)
        self.schemas.append(schema)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return {schema["required"][0]: reply} if isinstance(reply, list) else reply


class ScriptedJudge:
    """Answers every call with `verdicts`, or raises it if it is an exception."""

    name = "judge"

    def __init__(self, verdicts):
        self.verdicts = verdicts
        self.prompts = []
        self.schemas = []
        self.usage = SimpleNamespace(input_tokens=7, output_tokens=3, calls=0)

    def complete_json(self, prompt, schema):
        self.usage.calls += 1
        self.prompts.append(prompt)
        self.schemas.append(schema)
        if isinstance(self.verdicts, Exception):
            raise self.verdicts
        return {"verdicts": self.verdicts}
