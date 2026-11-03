"""Password hashing and session tokens."""

import asyncio
import hashlib
import secrets

from pwdlib import PasswordHash

_hasher = PasswordHash.recommended()  # Argon2

# Checked when an email is unknown, so a failed login takes the same time either way, and
# nobody can use the timing to discover which emails have accounts.
_DUMMY_HASH = _hasher.hash("not-a-real-password")


async def hash_password(password: str) -> str:
    # Argon2 is slow on purpose. A thread keeps it from stalling every other request.
    return await asyncio.to_thread(_hasher.hash, password)


async def verify_password(password: str, password_hash: str | None) -> bool:
    """Whether `password` matches. With no hash, it does the same work and returns False."""
    matched = await asyncio.to_thread(_hasher.verify, password, password_hash or _DUMMY_HASH)
    return matched and password_hash is not None


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> str:
    """What the database stores, so a leaked table can't be used to sign in."""
    return hashlib.sha256(token.encode()).hexdigest()
