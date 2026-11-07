"""Daily AI budgets, and recording what each run spent.

Budgets are best effort: two simultaneous requests can both pass a check. The vendors' own
counters remain the final word.
"""

import logging
from collections.abc import Mapping, Sequence
from datetime import timedelta

from app.ai.models import ModelSpec, Role, RunModels, model_chain, plan_models
from app.ai.usage import RunUsage
from app.core.settings import Settings
from app.models import AiUsage, utcnow
from app.repositories.usage import UsageRepository

logger = logging.getLogger(__name__)

BUDGET_WINDOW = timedelta(hours=24)

GENERATE = "generate"
PROBLEM_CARDS = "problem_cards"
TUTOR = "tutor"
MATERIALS = "materials"
SUGGESTIONS = "suggestions"
MCP_SEARCH = "mcp_search"

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
        # Step 1: count each model's calls in the last 24 hours for every model in the chains
        # in one grouped query so walking the chains below needs no more trips to the database
        names = {spec.name for role in cost for spec in model_chain(role, self.settings)}  # a set
        spent = await self.usage.calls_by_model(names, utcnow() - BUDGET_WINDOW)  # calls per model

        # Step 2: walk each role's chain to the first model whose daily limit has room

        def with_room(
            role: Role, chain: Sequence[ModelSpec], picked: Mapping[Role, ModelSpec]
        ) -> ModelSpec | None:
            def has_room(spec: ModelSpec) -> bool:
                # The other roles already on this model take their share of its room first.
                shared = sum(
                    cost[other] for other, used in picked.items() if used == spec and other != role
                )
                # worst case is today's calls plus other roles' share, this run and the reserve
                needed = spent.get(spec.name, 0) + shared + cost[role] + reserve
                return needed <= self.settings.model_daily_limit(spec.name)  # about 90% of Google's

            return next(filter(has_room, chain), None)  # first fit in chain order or None

        # plan_models also keeps the judge stronger than the writer it checks
        models = plan_models(self.settings, cost, judged=judged, start=with_room)
        # Step 3: log where each role starts so a slow or failing model can be traced
        picked = ",".join(f"{role}={models.first(role).name}" for role in cost) if models else ""
        logger.info("models picked", extra={"models": picked or "none left"})
        return models

    async def within_model_limits(
        self, cost: Mapping[Role, int], reserve: int = 0, *, judged: Role | None = None
    ) -> bool:
        """Whether every role has a model with room for `cost` plus `reserve`."""
        # a pre-check before queueing since the job picks its models again when it runs
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
        # Step 1: count this feature's calls in the last 24 hours for the site and the user
        calls = sum(cost.values())  # the run's worst case across all its roles
        if site_limit is None:  # no site cap for this feature so skip the site-wide count
            site, own = 0, await self.user_feature_calls(feature, user_id)
        else:
            site, own = await self.feature_calls(feature, user_id)  # both counts in one query
        counts = {"feature": feature, "calls": calls, "user_calls": own, "user_limit": user_limit}
        if site_limit is not None:
            counts |= {"site_calls": site, "site_limit": site_limit}
        logger.info("budget checked", extra=counts)

        # Step 2: refuse if this run would pass the site's or the user's limit
        if site_limit is not None and site + calls > site_limit:  # site checked first
            return SITE, None
        if own + calls > user_limit:
            return USER, None

        # Step 3: pick each role's first model with room None means a role has none left
        models = await self.pick_models(cost, reserve, judged=judged)
        # no model left is a site-wide limit to the learner not their own
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
        # Step 1: one row per role and model that made a call with its tokens
        for usage in run.roles:  # roles with 0 calls are left out so refused calls cost nothing
            logger.info(
                "usage recorded",
                extra={
                    "feature": feature,
                    "role": str(usage.role),
                    "model": usage.model,
                    "calls": usage.calls,
                    "input_tokens": usage.input_tokens,
                    "output_tokens": usage.output_tokens,
                },
            )
            self.usage.add(  # added to the session only so the caller's commit writes it
                AiUsage(
                    feature=feature,
                    role=usage.role,
                    model=usage.model,
                    user_id=user_id,
                    deck_id=deck_id,
                    prompt_version=prompt_version,  # compares spending across prompt changes
                    calls=usage.calls,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                )
            )
