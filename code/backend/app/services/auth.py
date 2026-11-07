"""Signing up, signing in and sessions."""

import logging
from datetime import timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, Unauthorized
from app.core.security import (
    hash_password,
    hash_token,
    new_session_token,
    token_hashes,
    verify_password,
)
from app.core.settings import Settings
from app.models import User, UserSession, utcnow
from app.repositories.users import UserRepository
from app.schemas.auth import MAX_PASSWORD_LENGTH, LoginRequest, RegisterRequest

logger = logging.getLogger(__name__)

ALREADY_REGISTERED = "That email is already registered."
INVALID_CREDENTIALS = "Invalid email or password."  # one message so no hint which emails exist


class AuthService:
    def __init__(self, session: AsyncSession, users: UserRepository, settings: Settings):
        self.session = session  # one request's transaction so nothing saves until commit
        self.users = users
        self.settings = settings

    async def register(self, body: RegisterRequest) -> tuple[User, str]:
        """The new user, and a session token for their cookie."""
        # Step 1: refuse an email that's already registered
        if await self.users.get_by_email(body.email) is not None:  # check before paying for a hash
            logger.info("register refused", extra={"reason": "email_taken"})
            raise Conflict(ALREADY_REGISTERED)  # 409 to the client

        # Step 2: save the user with a hash of their password never the password itself
        user = User(
            email=body.email,  # already normalized by the schema
            display_name=body.display_name,
            # Argon2 hashing runs in a thread so it doesn't block the event loop
            password_hash=await hash_password(body.password),
        )
        try:
            await self.users.add(user)  # flush runs the INSERT now so the user gets its id
        except IntegrityError:  # two sign-ups for one email race and the unique index rejects one
            await self.session.rollback()  # the failed INSERT spoiled the transaction
            logger.info("register refused", extra={"reason": "email_taken"})
            raise Conflict(ALREADY_REGISTERED) from None  # 409 with from None hiding the SQL error

        # Step 3: sign them in with a new session
        token = await self._start_session(user)  # random token only its hash stored
        await self.session.commit()  # user and session saved together or neither
        logger.info("user registered", extra={"user_id": user.id})
        return user, token  # router puts the token in an HttpOnly cookie

    async def login(self, body: LoginRequest) -> tuple[User, str]:
        """The user, and a session token for their cookie."""
        # Step 1: refuse an overlong password before hashing since no stored one can match it
        if len(body.password) > MAX_PASSWORD_LENGTH:  # blocks a CPU-burning DoS with huge input
            logger.info("login refused", extra={"reason": "password_too_long"})
            raise Unauthorized(INVALID_CREDENTIALS)  # 401 same message as a wrong password

        # Step 2: check the password and check unknown emails too so both cases take as long
        user = await self.users.get_by_email(body.email)
        password_hash = user.password_hash if user else None  # None for an unknown email
        # None is checked against a dummy hash with the same timing so emails can't be probed
        if not await verify_password(body.password, password_hash):
            reason = "wrong_password" if user else "unknown_email"  # told apart in logs only
            logger.info("login refused", extra={"reason": reason})
            raise Unauthorized(INVALID_CREDENTIALS)  # 401 the same either way

        # Step 3: clear the user's expired sessions then start a new one
        await self.users.delete_expired_sessions(user.id, utcnow())  # one DELETE for all
        token = await self._start_session(user)  # random token only its hash stored
        await self.session.commit()  # cleanup and new session in one transaction
        logger.info("user logged in", extra={"user_id": user.id})
        return user, token  # router puts the token in an HttpOnly cookie

    async def logout(self, token: str | None) -> None:
        """Logging out twice isn't an error."""
        if token:  # no cookie means nothing to end
            await self.users.delete_session(token_hashes(token))  # found by its hash
            await self.session.commit()

    async def user_for_token(self, token: str | None) -> User:
        # Step 1: find the session's user if the cookie has a token
        user = None
        if token:
            # one query for the user only while the session hasn't expired
            user = await self.users.get_by_session(token_hashes(token), utcnow())
        # Step 2: refuse a missing, unknown or expired session
        if user is None:
            raise Unauthorized("Authentication required.")  # 401 sends the page to login
        return user  # the CurrentUser dependency hands it to the route

    async def _start_session(self, user: User) -> str:
        # Step 1: make a random token for the cookie
        token = new_session_token()  # 32 random bytes from `secrets` so it's unguessable
        # Step 2: store only its hash with an expiry
        await self.users.add_session(
            UserSession(
                # a keyed hash so a leaked table can't be used to sign in
                token_hash=hash_token(token),
                user_id=user.id,
                expires_at=utcnow() + timedelta(days=self.settings.session_days),
            )
        )
        return token  # the raw token goes only to the cookie never the database
