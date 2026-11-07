"""Personal access tokens for MCP clients.

These routes take only the session cookie. A leaked token can't be used to make more tokens.
"""

from fastapi import APIRouter, status

from app.dependencies import ApiTokenServiceDep, CurrentUser
from app.schemas.api_tokens import ApiTokenCreate, ApiTokenCreated, ApiTokenRead

router = APIRouter(prefix="/api/tokens", tags=["tokens"])


@router.get("")
async def list_tokens(user: CurrentUser, service: ApiTokenServiceDep) -> list[ApiTokenRead]:
    return await service.list_tokens(user)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_token(
    body: ApiTokenCreate, user: CurrentUser, service: ApiTokenServiceDep
) -> ApiTokenCreated:
    return await service.create(user, body)


@router.delete("/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_token(token_id: int, user: CurrentUser, service: ApiTokenServiceDep) -> None:
    await service.revoke(user, token_id)
