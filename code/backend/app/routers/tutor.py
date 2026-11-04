"""The deck tutor. Someone else's deck answers 404, never 403."""

from fastapi import APIRouter, Response, status

from app.dependencies import CurrentUser, OwnedDeck, TutorServiceDep
from app.schemas.tutor import ProposalDecision, TutorMessageCreate, TutorView

router = APIRouter(prefix="/api/decks/{deck_id}/tutor", tags=["tutor"])


@router.get("")
async def get_tutor(deck: OwnedDeck, service: TutorServiceDep) -> TutorView:
    return await service.view(deck)


@router.post("/messages")
async def send_message(
    deck: OwnedDeck, body: TutorMessageCreate, user: CurrentUser, service: TutorServiceDep
) -> TutorView:
    return await service.send_message(deck, user, body.text)


@router.post("/proposal")
async def decide_proposal(
    deck: OwnedDeck, body: ProposalDecision, user: CurrentUser, service: TutorServiceDep
) -> TutorView:
    return await service.decide(deck, user, body.proposal_id, body.accept)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def reset_tutor(deck: OwnedDeck, service: TutorServiceDep) -> Response:
    await service.reset(deck)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
