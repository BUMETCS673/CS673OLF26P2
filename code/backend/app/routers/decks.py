"""Decks. Someone else's deck answers 404, never 403."""

from fastapi import APIRouter, status

from app.dependencies import CurrentUser, DeckServiceDep
from app.schemas.decks import DeckCreate, DeckRead, DeckUpdate

router = APIRouter(prefix="/api/decks", tags=["decks"])


@router.get("")
async def list_decks(user: CurrentUser, service: DeckServiceDep) -> list[DeckRead]:
    return await service.list_decks(user)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_deck(body: DeckCreate, user: CurrentUser, service: DeckServiceDep) -> DeckRead:
    return await service.create(user, body)


@router.get("/{deck_id}")
async def get_deck(deck_id: int, user: CurrentUser, service: DeckServiceDep) -> DeckRead:
    return await service.get(deck_id, user)


@router.patch("/{deck_id}")
async def update_deck(
    deck_id: int, body: DeckUpdate, user: CurrentUser, service: DeckServiceDep
) -> DeckRead:
    return await service.update(deck_id, user, body)


@router.delete("/{deck_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_deck(deck_id: int, user: CurrentUser, service: DeckServiceDep) -> None:
    await service.delete(deck_id, user)
