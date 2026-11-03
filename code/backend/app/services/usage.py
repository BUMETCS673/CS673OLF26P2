"""Records every AI call, and answers budget questions from that record.

Budgets are best effort: two simultaneous requests can both pass a check, and a call lost to a
crash mid-run is never recorded. Google's own counters remain the final word.
"""

from collections.abc import Mapping
from datetime import timedelta

from flask import current_app
from sqlalchemy import func, select

from app.ai.provider import Provider, Role, model_name
from app.extensions import db
from app.models import AiUsage, utcnow

CAP_WINDOW = timedelta(hours=24)  # every budget is rolling (rule 5)

GENERATE = "generate"
LEECH = "leech"
TUTOR = "tutor"


def _calls(*conditions) -> int:
    return db.session.scalar(
        select(func.coalesce(func.sum(AiUsage.calls), 0)).where(
            AiUsage.created_at > utcnow() - CAP_WINDOW, *conditions
        )
    )


def feature_calls(feature: str, user_id: int | None = None) -> int:
    """A feature's calls in the window, across the site or for one user."""
    conditions = [AiUsage.feature == feature]
    if user_id is not None:
        conditions.append(AiUsage.user_id == user_id)
    return _calls(*conditions)


def _model_limit(model: str) -> int:
    config = current_app.config
    return config["AI_MODEL_DAILY_LIMITS"].get(model, config["AI_MODEL_DAILY_LIMIT"])


def within_model_limits(cost: Mapping[Role, int], reserve: int = 0) -> bool:
    """Whether each model has room for `cost`, a request's worst case, plus `reserve` to spare."""
    by_model: dict[str, int] = {}
    for role, calls in cost.items():
        model = model_name(role)
        by_model[model] = by_model.get(model, 0) + calls
    return all(
        _calls(AiUsage.model == model) + calls + reserve <= _model_limit(model)
        for model, calls in by_model.items()
    )


def record_usage(
    feature: str,
    user_id: int,
    deck_id: int,
    writer: Provider | None,
    judge: Provider | None = None,
    prompt_version: str | None = None,
) -> None:
    """Add a row per provider that made a call, including failed calls. The caller commits."""
    for role, provider in ((Role.WRITER, writer), (Role.JUDGE, judge)):
        if provider is not None and provider.usage.calls:
            db.session.add(AiUsage(
                feature=feature,
                role=role.value,
                model=provider.name,
                user_id=user_id,
                deck_id=deck_id,
                prompt_version=prompt_version,
                calls=provider.usage.calls,
                input_tokens=provider.usage.input_tokens,
                output_tokens=provider.usage.output_tokens,
            ))
