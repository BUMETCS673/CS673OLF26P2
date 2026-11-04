"""The FastAPI app. Run it with: uvicorn app.main:app"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from langchain_core.tracers.langchain import wait_for_all_tracers

from app.ai.checkpoints import close_checkpointers
from app.ai.models import check_model_chains
from app.core.database import get_engine
from app.core.errors import register_error_handlers
from app.core.logs import configure_logging
from app.core.redis import get_redis
from app.core.requests import RequestMiddleware
from app.core.settings import get_settings
from app.core.telemetry import start_telemetry
from app.routers import (
    auth,
    cards,
    decks,
    generations,
    health,
    jobs,
    materials,
    problem_cards,
    study,
    tutor,
)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Set up logging and telemetry, and check the model chains, on startup. On shutdown, send
    waiting traces, metrics and logs, and close the pools."""
    settings = get_settings()
    configure_logging(settings)
    stop_telemetry = start_telemetry("api")
    check_model_chains(settings)
    yield
    await asyncio.to_thread(wait_for_all_tracers)
    await asyncio.to_thread(stop_telemetry)
    await close_checkpointers()
    await get_redis().aclose()
    await get_engine().dispose()


app = FastAPI(title="Cadence", lifespan=lifespan)
app.add_middleware(RequestMiddleware)
register_error_handlers(app)
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(decks.router)
app.include_router(cards.router)
app.include_router(study.router)
app.include_router(jobs.router)
app.include_router(materials.router)
app.include_router(generations.router)
app.include_router(problem_cards.router)
app.include_router(tutor.router)
