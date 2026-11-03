"""Generating cards. Someone else's deck or batch answers 404, never 403."""

from fastapi import APIRouter, status

from app.dependencies import CurrentUser, GenerationServiceDep
from app.schemas.generations import (
    Accepted,
    Decision,
    GenerateRequest,
    GenerationRead,
    JobStarted,
    Suggestions,
)

router = APIRouter(prefix="/api", tags=["generations"])


@router.post("/decks/{deck_id}/generate", status_code=status.HTTP_202_ACCEPTED)
async def generate(
    deck_id: int, body: GenerateRequest, user: CurrentUser, service: GenerationServiceDep
) -> JobStarted:
    """Follow the job. When it's done, its result holds the `generation_id` to read."""
    return JobStarted(job_id=await service.start(deck_id, user, body))


@router.post("/decks/{deck_id}/suggestions")
async def suggest(deck_id: int, user: CurrentUser, service: GenerationServiceDep) -> Suggestions:
    """Up to 3 topics to learn next. One short call that saves nothing, so it isn't a job."""
    return Suggestions(topics=await service.suggest(deck_id, user))


@router.post("/generations/{generation_id}/accept", status_code=status.HTTP_201_CREATED)
async def accept(
    generation_id: int, body: Decision, user: CurrentUser, service: GenerationServiceDep
) -> Accepted:
    return await service.accept(generation_id, user, body.indexes)


@router.post("/generations/{generation_id}/reject")
async def reject(
    generation_id: int, body: Decision, user: CurrentUser, service: GenerationServiceDep
) -> GenerationRead:
    return await service.reject(generation_id, user, body.indexes)


@router.get("/generations/{generation_id}")
async def get_generation(
    generation_id: int, user: CurrentUser, service: GenerationServiceDep
) -> GenerationRead:
    return await service.get(generation_id, user)
