"""Decks. Someone else's deck answers 404, never 403."""

from fastapi import APIRouter, status

from app.dependencies import CurrentUser, DeckServiceDep, OwnedDeck
from app.schemas.decks import DeckCreate, DeckRead, DeckUpdate

router = APIRouter(prefix="/api/decks", tags=["decks"])


@router.get("")
async def list_decks(user: CurrentUser, service: DeckServiceDep) -> list[DeckRead]:
    return await service.list_decks(user)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_deck(body: DeckCreate, user: CurrentUser, service: DeckServiceDep) -> DeckRead:
    return await service.create(user, body)


@router.get("/{deck_id}")
async def get_deck(deck: OwnedDeck, service: DeckServiceDep) -> DeckRead:
    return await service.get(deck)


@router.patch("/{deck_id}")
async def update_deck(deck: OwnedDeck, body: DeckUpdate, service: DeckServiceDep) -> DeckRead:
    return await service.update(deck, body)


@router.delete("/{deck_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_deck(deck: OwnedDeck, service: DeckServiceDep) -> None:
    await service.delete(deck)
