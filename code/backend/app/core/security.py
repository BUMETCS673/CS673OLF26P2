"""Password hashing and the random tokens for sessions and MCP clients."""

import asyncio
import hashlib
import hmac
import secrets
from datetime import timedelta

from pwdlib import PasswordHash

from app.core.settings import get_settings

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


API_TOKEN_PREFIX = "cad_"  # makes a leaked token easy to spot in logs and secret scanners
# how stale a token's last_used_at can get before a request records a new use
LAST_USED_PRECISION = timedelta(minutes=5)


def new_api_token() -> str:
    return API_TOKEN_PREFIX + secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """What the database stores, so a leaked table can't be used to sign in.

    The tokens are random, so a fast hash is enough. The secret key also means a stolen table
    can't be checked against guesses without the server's environment.
    """
    return _keyed_hash(get_settings().token_hash_key, token)


def token_hashes(token: str) -> list[str]:
    """The token's hash under the current key first, then under each old key still accepted."""
    settings = get_settings()
    old_keys = [key.strip() for key in settings.token_hash_old_keys.split(",") if key.strip()]
    return [_keyed_hash(key, token) for key in [settings.token_hash_key, *old_keys]]


def _keyed_hash(key: str, token: str) -> str:
    return hmac.new(key.encode(), token.encode(), hashlib.sha256).hexdigest()  # 64 hex characters
