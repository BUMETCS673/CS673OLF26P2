"""The tasks workers run, and the relay that runs alongside them.

Start a worker with: taskiq worker app.jobs.broker:broker app.jobs.tasks
"""

import asyncio
from contextlib import suppress
from functools import partial
from typing import Any

from langchain_core.tracers.langchain import wait_for_all_tracers
from taskiq import TaskiqEvents, TaskiqState

from app.ai.checkpoints import close_checkpointers
from app.ai.knowledge.cache import RedisByteStore
from app.ai.models import check_model_chains
from app.core.database import get_engine, get_session_factory
from app.core.logs import configure_logging
from app.core.redis import get_redis
from app.core.settings import get_settings
from app.core.telemetry import start_telemetry
from app.jobs.broker import broker
from app.jobs.card_embedding import embed_cards
from app.jobs.cleanup import run_cleanup
from app.jobs.events import JobEvents
from app.jobs.execution import Handler, JobContext, run_job
from app.jobs.generation import generate_cards, write_cards
from app.jobs.indexing import index_material
from app.jobs.problem_cards import review_problem_cards
from app.jobs.relay import run_relay
from app.models.job import EMBED_CARDS, GENERATE_CARDS, INDEX_MATERIAL, REVIEW_PROBLEM_CARDS


async def _index_material(context: JobContext) -> dict[str, Any] | None:
    cache = RedisByteStore(get_redis())  # the embedding cache lets re-indexing skip repeat chunks
    return await index_material(context, get_engine(), get_settings(), cache)


async def _generate_cards(context: JobContext) -> dict[str, Any]:
    settings = get_settings()
    cache = RedisByteStore(get_redis())
    # partial gives the graph a one-argument writer with its dependencies bound here
    write = partial(write_cards, engine=get_engine(), settings=settings, cache=cache)
    return await generate_cards(context, settings, write)


async def _embed_cards(context: JobContext) -> dict[str, Any]:
    cache = RedisByteStore(get_redis())
    return await embed_cards(context, get_engine(), get_settings(), cache)


async def _review_problem_cards(context: JobContext) -> dict[str, Any] | None:
    return await review_problem_cards(context, get_settings())


# a job's `kind` column picks its handler so one Taskiq task serves every kind
HANDLERS: dict[str, Handler] = {
    REVIEW_PROBLEM_CARDS: _review_problem_cards,
    EMBED_CARDS: _embed_cards,
    INDEX_MATERIAL: _index_material,
    GENERATE_CARDS: _generate_cards,
}


@broker.task
async def ping() -> str:
    """Proves a worker is taking tasks."""
    return "pong"


@broker.task
async def execute_job(job_id: int) -> None:
    # only the id travels through Redis since the job's row in Postgres holds the rest
    events = JobEvents(get_redis())
    await run_job(job_id, get_session_factory(), HANDLERS, publish_event=events.publish)


async def _publish(job_id: int) -> None:
    # .kiq() adds it to the broker's stream instead of calling it directly
    await execute_job.kiq(job_id)


@broker.on_event(TaskiqEvents.WORKER_STARTUP)
async def start_relay(state: TaskiqState) -> None:
    """Sets up logging and telemetry, then checks the model chains, so a bad one stops the
    worker before it takes a job."""
    settings = get_settings()
    # Step 1: logs and metrics first so startup problems are recorded
    configure_logging(settings)
    state.stop_telemetry = start_telemetry("worker")  # kept on state to flush at shutdown
    # Step 2: fail fast on a misconfigured model chain before any job is taken
    check_model_chains(settings)
    # Step 3: run the relay beside the tasks in this same event loop
    state.relay = asyncio.create_task(  # a background task so startup returns at once
        run_relay(settings.database_url, get_session_factory(), _publish)
    )
    # Step 4: clean up expired OAuth rows every hour, also in the background
    state.cleanup = asyncio.create_task(run_cleanup(get_session_factory()))


@broker.on_event(TaskiqEvents.WORKER_SHUTDOWN)
async def stop_relay(state: TaskiqState) -> None:
    """In this order, since the relay uses the database until it stops."""
    # Step 1: stop the relay and the cleanup, and wait for them to finish their current work
    for task in (state.relay, state.cleanup):
        task.cancel()
        with suppress(asyncio.CancelledError):  # cancelling raises this inside the task
            await task
    # Step 2: flush what's still buffered in threads since both calls block
    await asyncio.to_thread(wait_for_all_tracers)  # LangSmith traces
    await asyncio.to_thread(state.stop_telemetry)  # the last metrics and logs
    # Step 3: close the connections last since the steps above may still use them
    await close_checkpointers()  # LangGraph's Postgres pools
    await get_redis().aclose()
    await get_engine().dispose()  # SQLAlchemy's pool
