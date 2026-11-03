"""Measures search quality with the real embedding model, as a LangSmith experiment.

    python -m evals.retrieval

Needs GEMINI_API_KEY, LANGSMITH_API_KEY and a migrated database. Search results go to LangSmith, and
the tables printed at the end are for choosing MIN_SIMILARITY and NEAR_DUPLICATE_SIMILARITY. It only
reports, with no pass mark yet, and exits with 1 only if a case couldn't run.
"""

import asyncio
import json
import sys
from typing import Any

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_postgres import PGVectorStore
from langsmith import Client
from langsmith.evaluation import aevaluate
from sqlalchemy import text

from app.ai.knowledge.retrieval import MIN_SIMILARITY, KnowledgeRetriever
from app.ai.knowledge.store import create_store
from app.ai.models import Role, load_embeddings, model_name
from app.ai.prompting import version_of
from app.core.database import get_engine
from app.core.settings import get_settings
from app.jobs.card_embedding import _dot, _unit
from app.repositories.knowledge import NEAR_DUPLICATE_SIMILARITY
from evals.retrieval_cases import CARD_PAIRS, PASSAGES, SEARCH_CASES

K = 5
CUTOFFS = [value / 100 for value in range(30, 85, 5)]
DUPLICATE_THRESHOLDS = [0.85, 0.9, 0.93, 0.95, 0.97, 0.98, 0.99]

# Its own label, so these chunks never appear in a real search or mix with real ones here.
_STORED_AS = "retrieval-eval"
_FILTERS = {"embedding_model": _STORED_AS, "shared": True}


def rank_of(found: list[str], passage: str) -> int | None:
    return found.index(passage) + 1 if passage in found else None


def scores(inputs: dict, outputs: dict) -> dict:
    if inputs["expected"] is None:
        return {"results": [{"key": "refused", "score": outputs["returned"] == 0}]}
    rank = outputs["rank"]
    return {
        "results": [
            {"key": "hit", "score": rank is not None},
            {"key": "reciprocal_rank", "score": 1 / rank if rank else 0},
        ]
    }


def sweep(kept: list[float], refused: list[float], thresholds: list[float]) -> list[tuple]:
    """For each threshold, how many of `kept` reach it and how many of `refused` don't."""
    return [
        (threshold, sum(value >= threshold for value in kept), sum(v < threshold for v in refused))
        for threshold in thresholds
    ]


def _table(heading: str, kept: list[float], refused: list[float], thresholds: list[float]) -> str:
    rows = [heading, f"  threshold  of {len(kept)} kept  of {len(refused)} refused"]
    for threshold, kept_count, refused_count in sweep(kept, refused, thresholds):
        rows.append(f"  {threshold:9.2f}  {kept_count:9}  {refused_count:12}")
    return "\n".join(rows)


def search_report(outcomes: list[dict]) -> str:
    """Metrics at today's cutoff, each case's closest match, and what other cutoffs would do."""
    answerable = [outcome for outcome in outcomes if outcome["expected"] is not None]
    off_topic = [outcome for outcome in outcomes if outcome["expected"] is None]
    hits = sum(outcome["rank"] is not None for outcome in answerable)
    mrr = sum(1 / outcome["rank"] for outcome in answerable if outcome["rank"]) / len(answerable)
    refused = sum(outcome["returned"] == 0 for outcome in off_topic)
    lines = [
        f"At the {MIN_SIMILARITY} cutoff: hit rate at {K} {hits}/{len(answerable)}, "
        f"MRR {mrr:.2f}, off topic refused {refused}/{len(off_topic)}.",
    ]
    for outcome in sorted(outcomes, key=lambda item: item["closest"]):
        answer = "off topic" if outcome["expected"] is None else f"rank {outcome['rank']}"
        lines.append(f"  {outcome['closest']:.3f}  {outcome['name']} ({answer})")
    lines.append(
        _table(
            "Search cutoffs, from the closest match alone. An exact word match can still get past:",
            [outcome["closest"] for outcome in answerable],
            [outcome["closest"] for outcome in off_topic],
            CUTOFFS,
        )
    )
    return "\n".join(lines)


def duplicates_report(pairs: list[dict]) -> str:
    lines = [f"Card pairs, with the threshold at {NEAR_DUPLICATE_SIMILARITY}:"]
    for pair in sorted(pairs, key=lambda item: item["similarity"]):
        kind = "same fact" if pair["same"] else "different"
        lines.append(f"  {pair['similarity']:.3f}  {pair['name']} ({kind})")
    lines.append(
        _table(
            "Duplicate thresholds:",
            [pair["similarity"] for pair in pairs if pair["same"]],
            [pair["similarity"] for pair in pairs if not pair["same"]],
            DUPLICATE_THRESHOLDS,
        )
    )
    return "\n".join(lines)


async def run_search(
    case: dict, retriever: KnowledgeRetriever, store: PGVectorStore, embeddings: Embeddings
) -> dict[str, Any]:
    vector = await embeddings.aembed_query(case["query"])
    closest = await store.asimilarity_search_with_score_by_vector(
        vector, k=1, filter=_FILTERS, hybrid_search_config=None
    )
    found = [document.page_content for document in await retriever.ainvoke(case["query"])]
    expected = case["expected"]
    return {
        "name": case["name"],
        "expected": expected,
        "closest": 1 - closest[0][1],
        "returned": len(found),
        "rank": rank_of(found, PASSAGES[expected]) if expected else None,
    }


async def compare_pairs(embeddings: Embeddings) -> list[dict]:
    """Embedded as documents, as cards are when they're checked for duplicates."""
    texts = [text_ for pair in CARD_PAIRS for text_ in (pair["first"], pair["second"])]
    vectors = await embeddings.aembed_documents(texts)
    return [
        {**pair, "similarity": _dot(_unit(vectors[2 * index]), _unit(vectors[2 * index + 1]))}
        for index, pair in enumerate(CARD_PAIRS)
    ]


def _dataset(client: Client) -> str:
    """Named after its contents, so changing a case makes a new dataset, not a mixed one."""
    contents = json.dumps([PASSAGES, SEARCH_CASES], sort_keys=True)
    name = f"cadence-retrieval-{version_of(contents)}"
    if not client.has_dataset(dataset_name=name):
        dataset = client.create_dataset(name)
        for case in SEARCH_CASES:
            client.create_example(inputs=case, dataset_id=dataset.id)
    return name


async def main() -> int:
    settings = get_settings()
    engine = get_engine()
    embeddings = load_embeddings(settings)
    store = await create_store(engine, embeddings)
    retriever = KnowledgeRetriever(
        store=store, engine=engine, embeddings=embeddings, embedding_model=_STORED_AS, k=K
    )
    outcomes: list[dict] = []

    async def target(inputs: dict) -> dict:
        outcome = await run_search(inputs, retriever, store, embeddings)
        outcomes.append(outcome)
        return outcome

    try:
        await store.aadd_documents(
            [Document(page_content=passage, metadata={**_FILTERS}) for passage in PASSAGES.values()]
        )
        await aevaluate(
            target,
            data=_dataset(Client()),
            evaluators=[scores],
            experiment_prefix="retrieval",
            metadata={"model": model_name(Role.EMBEDDER, settings), "cutoff": MIN_SIMILARITY},
            max_concurrency=1,  # the rate limiter would only make the rest wait
        )
        print(search_report(outcomes))
        print(duplicates_report(await compare_pairs(embeddings)))
    finally:
        async with engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM knowledge_chunks WHERE embedding_model = :model"),
                {"model": _STORED_AS},
            )
        await engine.dispose()

    if len(outcomes) < len(SEARCH_CASES):
        print(f"Only {len(outcomes)} of {len(SEARCH_CASES)} search cases ran.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
