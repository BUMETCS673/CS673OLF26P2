"""Signing up, signing in and sessions."""

from datetime import timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, Unauthorized
from app.core.security import (
    hash_password,
    hash_session_token,
    new_session_token,
    verify_password,
)
from app.core.settings import Settings
from app.models import User, UserSession, utcnow
from app.repositories.users import UserRepository
from app.schemas.auth import MAX_PASSWORD_LENGTH, LoginRequest, RegisterRequest

ALREADY_REGISTERED = "That email is already registered."
INVALID_CREDENTIALS = "Invalid email or password."


class AuthService:
    def __init__(self, session: AsyncSession, users: UserRepository, settings: Settings):
        self.session = session
        self.users = users
        self.settings = settings

    async def register(self, body: RegisterRequest) -> tuple[User, str]:
        """The new user, and a session token for their cookie."""
        if await self.users.get_by_email(body.email) is not None:
            raise Conflict(ALREADY_REGISTERED)

        user = User(
            email=body.email,
            display_name=body.display_name,
            password_hash=await hash_password(body.password),
        )
        try:
            await self.users.add(user)
        except IntegrityError:
            # Two registrations for one email at once: the unique constraint catches the loser.
            await self.session.rollback()
            raise Conflict(ALREADY_REGISTERED) from None
        token = await self._start_session(user)
        await self.session.commit()
        return user, token

    async def login(self, body: LoginRequest) -> tuple[User, str]:
        """The user, and a session token for their cookie."""
        # No stored password can be over the limit, so don't pay to hash one.
        if len(body.password) > MAX_PASSWORD_LENGTH:
            raise Unauthorized(INVALID_CREDENTIALS)
        user = await self.users.get_by_email(body.email)
        password_hash = user.password_hash if user else None
        if not await verify_password(body.password, password_hash):
            raise Unauthorized(INVALID_CREDENTIALS)

        await self.users.delete_expired_sessions(user.id, utcnow())
        token = await self._start_session(user)
        await self.session.commit()
        return user, token

    async def logout(self, token: str | None) -> None:
        """Logging out twice isn't an error."""
        if token:
            await self.users.delete_session(hash_session_token(token))
            await self.session.commit()

    async def user_for_token(self, token: str | None) -> User:
        user = None
        if token:
            user = await self.users.get_by_session(hash_session_token(token), utcnow())
        if user is None:
            raise Unauthorized("Authentication required.")
        return user

    async def _start_session(self, user: User) -> str:
        token = new_session_token()
        await self.users.add_session(
            UserSession(
                token_hash=hash_session_token(token),
                user_id=user.id,
                expires_at=utcnow() + timedelta(days=self.settings.session_days),
            )
        )
        return token
