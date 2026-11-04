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

CHAT_ROLES = (Role.WRITER, Role.JUDGE, Role.HELPER)
AGENT_ROLES = (Role.WRITER, Role.HELPER)


class Answer(BaseModel):
    answer: str


@tool
def look_up(topic: str) -> str:
    """Looks a topic up."""
    return topic


def _models_to_check(settings: Settings) -> dict[ModelSpec, tuple[Role, bool]]:
    """Each model once, with a role it's used in and whether any of its roles needs tools."""
    checks: dict[ModelSpec, tuple[Role, bool]] = {}
    for role in CHAT_ROLES:
        for spec in model_chain(role, settings):
            first_role, needs_tools = checks.get(spec, (role, False))
            checks[spec] = (first_role, needs_tools or role in AGENT_ROLES)
    return checks


async def _check(spec: ModelSpec, role: Role, needs_tools: bool, settings: Settings) -> str:
    """What went wrong, or "ok"."""
    model = load_chat_model(role, settings, models=RunModels({role: (spec,)}))
    try:
        reply = await structured_reply(model, Answer, [HumanMessage("Reply with the answer: ok")])
        if reply is None:
            return "no reply in the schema"
        if needs_tools:
            with ai_errors():
                message = await model.bind_tools([look_up]).ainvoke(
                    [HumanMessage("Use the look_up tool to look up cells.")]
                )
            if not message.tool_calls:
                return "no tool call"
    except (AIRateLimited, AIUnavailable) as error:
        return type(error).__name__
    return "ok"


async def main() -> int:
    settings = get_settings()
    configure_logging(settings)
    failures = 0
    for spec, (role, needs_tools) in _models_to_check(settings).items():
        outcome = await _check(spec, role, needs_tools, settings)
        checked = "schema and tools" if needs_tools else "schema"
        print(f"{spec.name:<28} {checked:<18} {outcome}")
        failures += outcome != "ok"
    print(f"{failures} model(s) failed.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
