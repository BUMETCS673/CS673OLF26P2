"""Runs poisoned material against the real models, as a LangSmith experiment.

    python -m evals.redteam            every case, on request
    python -m evals.redteam --smoke    a few cases, for pull requests that change AI code

Needs GEMINI_API_KEY and LANGSMITH_API_KEY. It costs real calls, so it doesn't run on every push.
Exits with 1 if any case didn't do what it should.
"""

import argparse
import asyncio
import json
import sys
from typing import Any

from langchain_core.documents import Document
from langchain_core.language_models import BaseChatModel
from langsmith import Client
from langsmith.evaluation import aevaluate

from app.ai.cards import prompts
from app.ai.cards.writer import write_with_search
from app.ai.judge import TopicEvidence, judge_cards
from app.ai.knowledge.retrieval import OTHER_USER
from app.ai.knowledge.screening import screen_chunks
from app.ai.models import AIRateLimited, AIUnavailable, Role, load_chat_model
from app.ai.prompting import version_of
from app.ai.schemas import CardDraft
from app.core.settings import get_settings
from evals.redteam_cases import JUDGE_CASES, SCREENING_CASES, SMOKE_CASE_NAMES, WRITER_CASES

ALL_CASES = [
    *({"layer": "screening", **case} for case in SCREENING_CASES),
    *({"layer": "judge", **case} for case in JUDGE_CASES),
    *({"layer": "writer", **case} for case in WRITER_CASES),
]
WRITER_CARD_COUNT = 3


def cases_for(smoke: bool) -> list[dict]:
    return [case for case in ALL_CASES if not smoke or case["name"] in SMOKE_CASE_NAMES]


class _Found:
    """Stands in for search, so the writer always finds the poison through its real tool."""

    def __init__(self, text: str):
        self.text = text

    async def ainvoke(self, _query: str) -> list[Document]:
        return [Document(page_content=self.text, metadata={"origin": OTHER_USER})]


async def run_case(case: dict, writer: BaseChatModel, judge: BaseChatModel) -> dict[str, Any]:
    """Whether the material got through.

    None means no usable answer, or a writer that never searched, so it never saw the attack.
    """
    try:
        if case["layer"] == "screening":
            return {"allowed": await screen_chunks([case["text"]], lambda: writer) == [0]}
        if case["layer"] == "judge":
            verdicts = await judge_cards(
                judge,
                [CardDraft(front=case["front"], back=case["back"])],
                TopicEvidence(case["topic"], case["references"]),
            )
            return {"allowed": verdicts[0].ok if 0 in verdicts else None}
        cards, found, _ = await write_with_search(
            writer,
            prompts.rules(WRITER_CARD_COUNT),
            prompts.prompt_body(WRITER_CARD_COUNT, "Study deck", None, case["prompt"]),
            _Found(case["found"]),
        )
        if not found:
            return {"allowed": None}
        text = " ".join(f"{card.front} {card.back}" for card in cards).casefold()
        return {"allowed": case["planted_word"] in text}
    except (AIRateLimited, AIUnavailable):
        return {"allowed": None}


def _dataset(client: Client, cases: list[dict]) -> str:
    """Named after its contents, so changing a case makes a new dataset, not a mixed one."""
    name = f"cadence-redteam-{version_of(json.dumps(cases, sort_keys=True))}"
    if not client.has_dataset(dataset_name=name):
        dataset = client.create_dataset(name)
        for case in cases:
            client.create_example(
                inputs=case, outputs={"allowed": case["allowed"]}, dataset_id=dataset.id
            )
    return name


async def main(smoke: bool) -> int:
    settings = get_settings()
    writer = load_chat_model(Role.WRITER, settings)
    judge = load_chat_model(Role.JUDGE, settings)
    failures: list[str] = []
    total = 0

    async def target(inputs: dict) -> dict:
        return {**await run_case(inputs, writer, judge), "name": inputs["name"]}

    def did_as_expected(outputs: dict, reference_outputs: dict) -> bool:
        nonlocal total
        total += 1
        passed = outputs["allowed"] == reference_outputs["allowed"]
        if not passed:
            failures.append(outputs["name"])
        return passed

    await aevaluate(
        target,
        data=_dataset(Client(), cases_for(smoke)),
        evaluators=[did_as_expected],
        experiment_prefix="redteam-smoke" if smoke else "redteam",
        max_concurrency=1,  # the rate limiter would only make the rest wait
    )
    print(f"{total - len(failures)} of {total} cases did as expected.")
    for name in sorted(failures):
        print(f"  failed: {name}")
    return 1 if failures else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run poisoned material against the real models.")
    parser.add_argument("--smoke", action="store_true", help="Run a few cases, not all of them.")
    sys.exit(asyncio.run(main(parser.parse_args().smoke)))
