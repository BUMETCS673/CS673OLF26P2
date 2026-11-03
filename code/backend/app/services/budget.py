"""Daily AI budgets, and recording what each run spent.

Budgets are best effort: two simultaneous requests can both pass a check. Google's own counters
remain the final word.
"""

from collections.abc import Mapping
from datetime import timedelta

from app.ai.models import Role, model_name
from app.ai.usage import RunUsage
from app.core.settings import Settings
from app.models import AiUsage, utcnow
from app.repositories.usage import UsageRepository

BUDGET_WINDOW = timedelta(hours=24)

GENERATE = "generate"
PROBLEM_CARDS = "problem_cards"
TUTOR = "tutor"
MATERIALS = "materials"
SUGGESTIONS = "suggestions"


class BudgetService:
    def __init__(self, usage: UsageRepository, settings: Settings):
        self.usage = usage
        self.settings = settings

    async def within_model_limits(self, cost: Mapping[Role, int], reserve: int = 0) -> bool:
        """Whether each model has room for `cost`, a run's worst case, plus `reserve` to spare."""
        since = utcnow() - BUDGET_WINDOW
        by_model: dict[str, int] = {}
        for role, calls in cost.items():
            model = model_name(role, self.settings)
            by_model[model] = by_model.get(model, 0) + calls
        spent = await self.usage.calls_by_model(by_model, since)
        return all(
            spent.get(model, 0) + calls + reserve <= self.settings.model_daily_limit(model)
            for model, calls in by_model.items()
        )

    async def feature_calls(self, feature: str, user_id: int) -> tuple[int, int]:
        """A feature's calls in the window, across the site and for one user."""
        return await self.usage.feature_calls(feature, utcnow() - BUDGET_WINDOW, user_id)

    async def user_feature_calls(self, feature: str, user_id: int) -> int:
        return await self.usage.user_feature_calls(feature, utcnow() - BUDGET_WINDOW, user_id)

    def record(
        self,
        feature: str,
        user_id: int,
        deck_id: int | None,
        run: RunUsage,
        prompt_version: str | None = None,
    ) -> None:
        """Add a row per role that made a call. The caller commits."""
        for usage in run.roles:
            self.usage.add(
                AiUsage(
                    feature=feature,
                    role=usage.role,
                    model=usage.model,
                    user_id=user_id,
                    deck_id=deck_id,
                    prompt_version=prompt_version,
                    calls=usage.calls,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                )
            )
