"""Lets public OAuth clients call the SDK's /revoke without sending a client_secret."""

from urllib.parse import parse_qsl

from starlette.types import ASGIApp, Message, Receive, Scope, Send

FORM_TYPE = b"application/x-www-form-urlencoded"


class RevocationForm:
    """Wraps the SDK's /revoke endpoint and adds an empty client_secret when it's missing.

    The SDK's form model requires that field even for clients registered without a secret, so
    Claude and other public clients would get a 400 without this.
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        headers = dict(scope.get("headers", []))  # ASGI headers are lowercase byte pairs
        if (
            scope["type"] != "http"
            or scope["method"] != "POST"
            or not headers.get(b"content-type", b"").startswith(FORM_TYPE)
        ):
            await self.app(scope, receive, send)
            return
        # Step 1: read the whole form, which the SDK would buffer anyway
        chunks = []
        more = True
        while more:
            message = await receive()
            if message["type"] == "http.disconnect":  # the client left, so nobody gets a reply
                return
            chunks.append(message.get("body", b""))
            more = message.get("more_body", False)
        body = b"".join(chunks)
        # Step 2: add the field only when it's missing so a real secret still gets checked
        fields = parse_qsl(body.decode(errors="replace"), keep_blank_values=True)
        if all(name != "client_secret" for name, _ in fields):
            body += b"&client_secret=" if body else b"client_secret="
        # Step 3: hand the SDK the new body with a matching Content-Length
        # only Content-Length is replaced so repeated headers like Cookie stay as they were
        kept = [(name, value) for name, value in scope["headers"] if name != b"content-length"]
        scope = {**scope, "headers": [*kept, (b"content-length", str(len(body)).encode())]}
        replayed = False

        async def replay() -> Message:
            nonlocal replayed
            if replayed:
                return await receive()  # later reads wait for the disconnect as usual
            replayed = True
            return {"type": "http.request", "body": body, "more_body": False}

        await self.app(scope, replay, send)
