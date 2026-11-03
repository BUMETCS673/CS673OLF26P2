"""Problem card reviews. Someone else's deck or review answers 404, never 403."""

from fastapi import APIRouter

from app.dependencies import CurrentUser, ProblemCardServiceDep
from app.schemas.problem_cards import (
    Decisions,
    DecisionsApplied,
    DeckReview,
    ProblemCardSummary,
)

router = APIRouter(prefix="/api", tags=["problem cards"])


@router.get("/problem-cards")
async def problem_card_summary(
    user: CurrentUser, service: ProblemCardServiceDep
) -> ProblemCardSummary:
    """A review starts by itself when a card crosses its limit, so this only reads."""
    return await service.summary(user)


@router.get("/decks/{deck_id}/problem-card-review")
async def deck_review(
    deck_id: int, user: CurrentUser, service: ProblemCardServiceDep
) -> DeckReview:
    return DeckReview(review=await service.pending_for_deck(deck_id, user))


@router.post("/problem-card-reviews/{review_id}/decisions")
async def decide(
    review_id: int, body: Decisions, user: CurrentUser, service: ProblemCardServiceDep
) -> DecisionsApplied:
    return await service.decide(review_id, user, body.decisions)
