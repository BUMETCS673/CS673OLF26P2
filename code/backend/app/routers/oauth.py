"""The parts of Cadence's OAuth sign-in that the frontend calls for consent and connected apps.

The SDK serves /authorize and /token itself. These routes take the session cookie. SameSite=lax
keeps that cookie off cross-site POSTs and another site can't approve a request for the user.
"""

from fastapi import APIRouter, status

from app.dependencies import CurrentUser, OAuthServiceDep, OAuthTokenServiceDep
from app.schemas.oauth import ConnectedApp, ConsentDecision, ConsentRead, ConsentResult

router = APIRouter(prefix="/api/oauth", tags=["oauth"])


@router.get("/consent/{request_id}")
async def get_consent(request_id: str, _: CurrentUser, service: OAuthServiceDep) -> ConsentRead:
    return await service.describe(request_id)


@router.post("/consent/{request_id}")
async def decide_consent(
    request_id: str, body: ConsentDecision, user: CurrentUser, service: OAuthServiceDep
) -> ConsentResult:
    return ConsentResult(redirect_url=await service.decide(request_id, user, body.approve))


@router.get("/apps")
async def list_apps(user: CurrentUser, service: OAuthTokenServiceDep) -> list[ConnectedApp]:
    return await service.connected_apps(user)


@router.delete("/apps/{client_id}", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_app(client_id: str, user: CurrentUser, service: OAuthTokenServiceDep) -> None:
    await service.disconnect(user, client_id)
