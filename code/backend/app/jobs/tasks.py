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
from app.core.database import get_engine, get_session_factory
from app.core.redis import get_redis
from app.core.settings import get_settings
from app.jobs.broker import broker
from app.jobs.card_embedding import embed_cards
from app.jobs.events import JobEvents
from app.jobs.execution import Handler, JobContext, run_job
from app.jobs.generation import generate_cards, write_cards
from app.jobs.indexing import index_material
from app.jobs.problem_cards import review_problem_cards
from app.jobs.relay import run_relay
from app.models.job import EMBED_CARDS, GENERATE_CARDS, INDEX_MATERIAL, REVIEW_PROBLEM_CARDS


async def _index_material(context: JobContext) -> dict[str, Any] | None:
    cache = RedisByteStore(get_redis())
    return await index_material(context, get_engine(), get_settings(), cache)


async def _generate_cards(context: JobContext) -> dict[str, Any]:
    settings = get_settings()
    write = partial(write_cards, engine=get_engine(), settings=settings)
    return await generate_cards(context, settings, write)


async def _embed_cards(context: JobContext) -> dict[str, Any]:
    cache = RedisByteStore(get_redis())
    return await embed_cards(context, get_engine(), get_settings(), cache)


async def _review_problem_cards(context: JobContext) -> dict[str, Any] | None:
    return await review_problem_cards(context, get_settings())


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
    events = JobEvents(get_redis())
    await run_job(job_id, get_session_factory(), HANDLERS, publish_event=events.publish)


async def _publish(job_id: int) -> None:
    await execute_job.kiq(job_id)


@broker.on_event(TaskiqEvents.WORKER_STARTUP)
async def start_relay(state: TaskiqState) -> None:
    state.relay = asyncio.create_task(
        run_relay(get_settings().database_url, get_session_factory(), _publish)
    )


@broker.on_event(TaskiqEvents.WORKER_SHUTDOWN)
async def stop_relay(state: TaskiqState) -> None:
    """In this order, since the relay uses the database until it stops."""
    state.relay.cancel()
    with suppress(asyncio.CancelledError):
        await state.relay
    await asyncio.to_thread(wait_for_all_tracers)
    await close_checkpointers()
    await get_redis().aclose()
    await get_engine().dispose()
