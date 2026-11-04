"""A study session. Intervals are always computed here, never by the frontend."""

from fastapi import APIRouter

from app.dependencies import CurrentUser, OwnedDeck, StudyServiceDep
from app.schemas.study import DueCards, ReviewRequest, StudyCardRead

router = APIRouter(prefix="/api", tags=["study"])


@router.get("/decks/{deck_id}/due")
async def due_cards(deck: OwnedDeck, service: StudyServiceDep) -> DueCards:
    return await service.due_cards(deck)


@router.post("/cards/{card_id}/review")
async def review_card(
    card_id: int, body: ReviewRequest, user: CurrentUser, service: StudyServiceDep
) -> StudyCardRead:
    return await service.review(card_id, user, body)
