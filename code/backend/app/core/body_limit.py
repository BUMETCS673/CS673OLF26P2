"""A cap on request bodies, so nobody can make the API read an endless body into memory."""

from fastapi import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

BODY_MAX = 1024 * 1024  # far above the biggest JSON body, 25 cards of 2,000 characters
TOO_LARGE = "The request body is too large."
OWN_LIMIT = "/api/materials"  # uploads check their own, much higher, limit as they stream


class BodyLimit:
    """Answers 413 once a body grows past BODY_MAX, counting what arrives.

    Counting covers a missing or false Content-Length, which a header check alone would trust.
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"].startswith(OWN_LIMIT):
            await self.app(scope, receive, send)
            return
        received = 0

        async def counted() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > BODY_MAX:
                    raise HTTPException(413, TOO_LARGE)  # the error handlers shape the reply
            return message

        await self.app(scope, counted, send)
