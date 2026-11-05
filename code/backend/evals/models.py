"""Calls each model in the role chains once: does its ID exist, and can it do what its roles need?

Every model must reply in a schema. The writer's and helper's models must also call a tool, since
they run as agents. Run it with: python -m evals.models
"""

import asyncio
import sys

from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from pydantic import BaseModel

from app.ai.models import (
    AIRateLimited,
    AIUnavailable,
    ModelSpec,
    Role,
    RunModels,
    ai_errors,
    load_chat_model,
    model_chain,
    structured_reply,
)
from app.core.logs import configure_logging
from app.core.settings import Settings, get_settings

CHAT_ROLES = (Role.WRITER, Role.JUDGE, Role.HELPER)  # the embedder isn't a chat model
AGENT_ROLES = (Role.WRITER, Role.HELPER)  # these run as agents so they must call tools


class Answer(BaseModel):  # the smallest schema so the check costs few tokens
    answer: str


@tool
def look_up(topic: str) -> str:
    """Looks a topic up."""
    return topic  # never actually run the check only needs the call


def _models_to_check(settings: Settings) -> dict[ModelSpec, tuple[Role, bool]]:
    """Each model once, with a role it's used in and whether any of its roles needs tools."""
    checks: dict[ModelSpec, tuple[Role, bool]] = {}  # keyed by model so each is called once
    for role in CHAT_ROLES:
        for spec in model_chain(role, settings):  # every model in every chain fallbacks too
            first_role, needs_tools = checks.get(spec, (role, False))  # keep the first role seen
            # a model shared by roles needs tools if any of its roles does
            checks[spec] = (first_role, needs_tools or role in AGENT_ROLES)
    return checks


async def _check(spec: ModelSpec, role: Role, needs_tools: bool, settings: Settings) -> str:
    """What went wrong, or "ok"."""
    # a chain of just this model so no fallback can hide its failure
    model = load_chat_model(role, settings, models=RunModels({role: (spec,)}))
    try:
        # Step 1: the model must reply in a schema which every role needs
        reply = await structured_reply(model, Answer, [HumanMessage("Reply with the answer: ok")])
        if reply is None:
            return "no reply in the schema"
        # Step 2: an agent's model must also call a tool when asked
        if needs_tools:
            with ai_errors():  # vendor errors become ours so they're caught below
                message = await model.bind_tools([look_up]).ainvoke(
                    [HumanMessage("Use the look_up tool to look up cells.")]
                )
            if not message.tool_calls:  # it answered in text instead
                return "no tool call"
    except (AIRateLimited, AIUnavailable) as error:  # a bad model ID shows up here as a 404
        return type(error).__name__  # the class only and the log line has the status
    return "ok"


async def main() -> int:
    settings = get_settings()
    configure_logging(settings)  # JSON lines so each failure shows its status in CI
    failures = 0
    # one at a time so the rate limiter never queues the checks
    for spec, (role, needs_tools) in _models_to_check(settings).items():
        outcome = await _check(spec, role, needs_tools, settings)
        checked = "schema and tools" if needs_tools else "schema"
        print(f"{spec.name:<28} {checked:<18} {outcome}")  # padded into aligned columns
        failures += outcome != "ok"  # True adds 1
    print(f"{failures} model(s) failed.")
    return 1 if failures else 0  # a non-zero exit fails the CI step


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
