"""Cards, under two paths: a deck's cards, and a card on its own."""

from fastapi import APIRouter, status

from app.dependencies import CardServiceDep, CurrentUser
from app.schemas.cards import CardCreate, CardRead, CardUpdate

router = APIRouter(prefix="/api", tags=["cards"])


@router.get("/decks/{deck_id}/cards", response_model=list[CardRead])
async def list_cards(deck_id: int, user: CurrentUser, service: CardServiceDep):
    return await service.list_cards(deck_id, user)


@router.post("/decks/{deck_id}/cards", status_code=status.HTTP_201_CREATED, response_model=CardRead)
async def create_card(deck_id: int, body: CardCreate, user: CurrentUser, service: CardServiceDep):
    return await service.create(deck_id, user, body)


@router.patch("/cards/{card_id}", response_model=CardRead)
async def update_card(card_id: int, body: CardUpdate, user: CurrentUser, service: CardServiceDep):
    return await service.update(card_id, user, body)


@router.post("/cards/{card_id}/report", status_code=status.HTTP_204_NO_CONTENT)
async def report_card(card_id: int, user: CurrentUser, service: CardServiceDep) -> None:
    await service.report(card_id, user)


@router.delete("/cards/{card_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_card(card_id: int, user: CurrentUser, service: CardServiceDep) -> None:
    await service.delete(card_id, user)
