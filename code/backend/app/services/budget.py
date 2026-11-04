"""Daily AI budgets, and recording what each run spent.

Budgets are best effort: two simultaneous requests can both pass a check. The vendors' own
counters remain the final word.
"""

from collections.abc import Mapping, Sequence
from datetime import timedelta

from app.ai.models import ModelSpec, Role, RunModels, model_chain, plan_models
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

# Which limit a run would pass.
SITE = "site"
USER = "user"


class BudgetService:
    def __init__(self, usage: UsageRepository, settings: Settings):
        self.usage = usage
        self.settings = settings

    async def pick_models(
        self, cost: Mapping[Role, int], reserve: int = 0, *, judged: Role | None = None
    ) -> RunModels | None:
        """The run's models, each role starting on its first model with room.

        Room means space for `cost`, a run's worst case, plus `reserve`, and roles that pick
        the same model share it. A run with a judge names the role whose cards it checks in
        `judged`. None means some role has no model left.
        """
        names = {spec.name for role in cost for spec in model_chain(role, self.settings)}
        spent = await self.usage.calls_by_model(names, utcnow() - BUDGET_WINDOW)

        def with_room(
            role: Role, chain: Sequence[ModelSpec], picked: Mapping[Role, ModelSpec]
        ) -> ModelSpec | None:
            def has_room(spec: ModelSpec) -> bool:
                # The other roles already on this model take their share of its room first.
                shared = sum(
                    cost[other] for other, used in picked.items() if used == spec and other != role
                )
                needed = spent.get(spec.name, 0) + shared + cost[role] + reserve
                return needed <= self.settings.model_daily_limit(spec.name)

            return next(filter(has_room, chain), None)

        return plan_models(self.settings, cost, judged=judged, start=with_room)

    async def within_model_limits(
        self, cost: Mapping[Role, int], reserve: int = 0, *, judged: Role | None = None
    ) -> bool:
        """Whether every role has a model with room for `cost` plus `reserve`."""
        return await self.pick_models(cost, reserve, judged=judged) is not None

    async def limit_reached(
        self,
        feature: str,
        user_id: int,
        cost: Mapping[Role, int],
        *,
        user_limit: int,
        site_limit: int | None = None,
        reserve: int = 0,
        judged: Role | None = None,
    ) -> tuple[str | None, RunModels | None]:
        """SITE or USER for the first limit a run of `cost` would pass, or else the models to use.

        A role with no model left counts as the site's limit. `judged` is as in `pick_models`.
        """
        calls = sum(cost.values())
        if site_limit is None:
            site, own = 0, await self.user_feature_calls(feature, user_id)
        else:
            site, own = await self.feature_calls(feature, user_id)
        if site_limit is not None and site + calls > site_limit:
            return SITE, None
        if own + calls > user_limit:
            return USER, None
        models = await self.pick_models(cost, reserve, judged=judged)
        return (None, models) if models is not None else (SITE, None)

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
