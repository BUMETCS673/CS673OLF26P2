"""The FastAPI app. Run it with: uvicorn app.main:app"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from langchain_core.tracers.langchain import wait_for_all_tracers
from mcp.server.auth.routes import REGISTRATION_PATH, REVOCATION_PATH

from app.ai.checkpoints import close_checkpointers
from app.ai.models import check_model_chains
from app.core.body_limit import BodyLimit
from app.core.database import get_engine
from app.core.errors import register_error_handlers
from app.core.logs import configure_logging
from app.core.redis import get_redis
from app.core.requests import RequestMiddleware
from app.core.settings import get_settings
from app.core.telemetry import start_telemetry
from app.mcp.limits import RegistrationLimit
from app.mcp.revocation import RevocationForm
from app.mcp.server import build_mcp_app, mcp_server
from app.routers import (
    api_tokens,
    auth,
    cards,
    decks,
    generations,
    health,
    jobs,
    materials,
    oauth,
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
    # the MCP route hands each request to tasks in this manager's task group
    async with mcp_server.session_manager.run():
        yield
    await asyncio.to_thread(wait_for_all_tracers)
    await asyncio.to_thread(stop_telemetry)
    await close_checkpointers()
    await get_redis().aclose()
    await get_engine().dispose()


app = FastAPI(title="Cadence", lifespan=lifespan)
app.add_middleware(BodyLimit)  # added first so it runs inside RequestMiddleware's logging
app.add_middleware(RequestMiddleware)
register_error_handlers(app)
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(api_tokens.router)
app.include_router(oauth.router)
app.include_router(decks.router)
app.include_router(cards.router)
app.include_router(study.router)
app.include_router(jobs.router)
app.include_router(materials.router)
app.include_router(generations.router)
app.include_router(problem_cards.router)
app.include_router(tutor.router)
# Exact routes instead of a mount keep our 404 shape for other unknown paths. The MCP app sees the
# full path and routes /api/mcp, the OAuth endpoints and the discovery files itself.
mcp_app = build_mcp_app()
for route in mcp_app.routes:
    # registration needs no sign-in and is the one path with its own rate limit
    endpoint = RegistrationLimit(mcp_app) if route.path == REGISTRATION_PATH else mcp_app
    if route.path == REVOCATION_PATH:
        endpoint = RevocationForm(mcp_app)  # public clients send no client_secret
    app.add_route(route.path, endpoint, include_in_schema=False)
