"""Each role's chain of models, and the plan of which models one run may use."""

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from app.ai.models.errors import NOT_CONFIGURED, AIUnavailable
from app.ai.models.vendors import FAKE, is_set_up
from app.core.settings import Settings


class Role(StrEnum):
    """What a model is used for. Each role has its own settings."""

    WRITER = "writer"
    JUDGE = "judge"
    HELPER = "helper"  # the high-volume calls, on a model with a larger quota
    EMBEDDER = "embedder"


def _vendor_and_model(role: Role, settings: Settings) -> tuple[str, str]:
    return (  # one pair of settings per role like ai_writer_provider and ai_writer_model
        getattr(settings, f"ai_{role}_provider"),
        getattr(settings, f"ai_{role}_model"),
    )


@dataclass(frozen=True)  # frozen makes specs hashable for sets and dict keys
class ModelSpec:
    vendor: str
    name: str


def model_chain(role: Role, settings: Settings) -> list[ModelSpec]:
    """The role's models in order of preference, starting with its own setting.

    The judge's chain is also the strength order: strongest first, and listing every model
    whose cards it checks. `check_model_chains` makes sure of that at startup.
    """
    vendor, model = _vendor_and_model(role, settings)
    if vendor == FAKE:  # one canned model for tests and local runs with no chain
        return [ModelSpec(FAKE, FAKE)]
    first = ModelSpec(vendor, model)
    fallbacks = getattr(settings, f"ai_{role}_fallbacks", "")  # "vendor:modelvendor:model"
    # split on the first ":" only so a model name may contain one
    rest = [ModelSpec(*item.strip().split(":", 1)) for item in fallbacks.split(",") if item.strip()]
    # A fallback that isn't set up is skipped, so a full model reads as a limit.
    return [first, *(spec for spec in rest if spec != first and is_set_up(spec.vendor, settings))]


JUDGED_ROLES = (Role.WRITER, Role.HELPER)  # the roles whose cards a judge checks


def judge_chain(settings: Settings, checked: Sequence[ModelSpec]) -> list[ModelSpec]:
    """The judge's models ranked above every one in `checked`, so it's always the stronger.

    A model the judge's chain doesn't rank is left out of the cut. That only happens when AI
    isn't set up, since `check_model_chains` refuses such a chain at startup.
    """
    chain = model_chain(Role.JUDGE, settings)
    if chain[0].vendor == FAKE:
        return chain
    ranks = [chain.index(spec) for spec in checked if spec in chain]  # each checked model's rank
    # cut above the strongest checked model so every judge left outranks them all
    return chain[: min(ranks)] if ranks else chain


def check_model_chains(settings: Settings) -> None:
    """Refuses to start with a judge that can't be ranked above each model it checks."""
    judge = model_chain(Role.JUDGE, settings)
    if not is_set_up(judge[0].vendor, settings):  # AI is off so there's nothing to check
        return
    for role in JUDGED_ROLES:
        for spec in model_chain(role, settings):
            # the judge's first model must outrank them so it can't be one of them
            if is_set_up(spec.vendor, settings) and spec not in judge[1:]:
                raise ValueError(  # fails the worker's startup catching a config error early
                    f"The judge's chain must list {spec.name}, the {role} model, after its "
                    "first model, so the judge can be ranked above it."
                )


@dataclass(frozen=True)
class RunModels:
    """The models each role may use in one run, in the order it tries them.

    Budgeting and loading both read this, so they can't disagree about a role's models.
    """

    chains: Mapping[Role, tuple[ModelSpec, ...]]

    def chain(self, role: Role) -> tuple[ModelSpec, ...]:
        return self.chains[role]

    def first(self, role: Role) -> ModelSpec:
        return self.chains[role][0]


# Where a role starts in `chain`, given the other roles' picks so far, or None if no model has
# room. It must not change anything, since the planner can try a role more than once.
StartPicker = Callable[[Role, Sequence[ModelSpec], Mapping[Role, ModelSpec]], ModelSpec | None]


def _first_model(
    _role: Role, chain: Sequence[ModelSpec], _picked: Mapping[Role, ModelSpec]
) -> ModelSpec | None:
    return chain[0] if chain else None


def plan_models(
    settings: Settings,
    roles: Iterable[Role],
    *,
    judged: Role | None = None,
    start: StartPicker = _first_model,
) -> RunModels | None:
    """Each role's models for one run: from the model `start` picks, down its chain.

    The judge plans last, from only the models above every one `judged` may use. If none of
    those has room, `judged` starts one model weaker and the judge tries again, since a weaker
    model's cards leave more judges ranked above them. None means some role had no model left.
    """
    roles = list(roles)  # iterated more than once below
    has_judge = Role.JUDGE in roles
    if has_judge and judged not in roles:  # a programming error not a runtime condition
        raise ValueError("A run with a judge must say which role's cards it checks.")
    picked: dict[Role, ModelSpec] = {}  # each role's starting model so far
    chains: dict[Role, tuple[ModelSpec, ...]] = {}

    def take(role: Role, chain: Sequence[ModelSpec]) -> bool:
        spec = start(role, chain, picked)  # e.g the first model with budget room
        if spec is None:
            return False
        picked[role] = spec
        # from the pick down which gives its fallbacks
        chains[role] = tuple(chain[chain.index(spec) :])
        return True

    # Step 1: every role other than the judge and the one it checks picks independently
    for role in roles:
        if role not in (Role.JUDGE, judged) and not take(role, model_chain(role, settings)):
            return None  # a role with no room means the run can't go ahead
    if judged is None or judged not in roles:
        return RunModels(chains)
    # Step 2: pick the checked role and a judge above it weakening the checked role until
    # a judge fits
    checked = model_chain(judged, settings)
    while take(judged, checked):
        if not has_judge or take(Role.JUDGE, judge_chain(settings, chains[judged])):
            return RunModels(chains)
        checked = checked[checked.index(picked[judged]) + 1 :]  # skip past this pick
    return None  # ran out of checked models


def first_models(
    settings: Settings, roles: Iterable[Role], *, judged: Role | None = None
) -> RunModels:
    """Each role's whole chain, for a run that goes ahead without checking budgets."""
    models = plan_models(settings, roles, judged=judged)  # start defaults to each chain's first
    if models is None:  # only a judge with no model above the one it checks
        raise AIUnavailable(NOT_CONFIGURED)
    return models


def model_name(role: Role, settings: Settings) -> str:
    """The name the role's first model is recorded under, without building a client."""
    return model_chain(role, settings)[0].name
