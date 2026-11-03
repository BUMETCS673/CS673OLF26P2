"""Signing up and signing in.

Register and login put a session cookie on the response. The frontend calls /me on page load,
to find out whether someone is still signed in.
"""

from fastapi import APIRouter, Response, status

from app.core.settings import get_settings
from app.dependencies import SESSION_COOKIE, AuthServiceDep, CurrentUser, SessionToken
from app.schemas.auth import LoginRequest, RegisterRequest, UserRead

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _set_session_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.session_days * 24 * 60 * 60,
        httponly=True,  # page scripts can't read it
        samesite="lax",  # other sites can't make requests as the user
        secure=settings.session_cookie_secure,
    )


@router.post("/register", status_code=status.HTTP_201_CREATED, response_model=UserRead)
async def register(body: RegisterRequest, response: Response, service: AuthServiceDep):
    user, token = await service.register(body)
    _set_session_cookie(response, token)
    return user


@router.post("/login", response_model=UserRead)
async def login(body: LoginRequest, response: Response, service: AuthServiceDep):
    user, token = await service.login(body)
    _set_session_cookie(response, token)
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response, service: AuthServiceDep, token: SessionToken = None) -> None:
    await service.logout(token)
    response.delete_cookie(SESSION_COOKIE)


@router.get("/me", response_model=UserRead)
async def me(user: CurrentUser):
    return user
