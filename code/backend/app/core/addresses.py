"""The caller's address behind the Cloudflare Worker and Render's proxy."""

from starlette.types import Scope

ADDRESS_MAX = 64  # longer than any IPv6 address


def client_address(scope: Scope) -> str:
    """The first X-Forwarded-For entry, which the Worker sets from Cloudflare's own header.

    Someone calling the backend directly can fake it, so limits keyed on it need another key too.
    """
    for name, value in scope["headers"]:  # ASGI headers are lowercase byte pairs
        if name == b"x-forwarded-for":
            first = value.decode(errors="replace").split(",")[0].strip()  # the original caller
            return first[:ADDRESS_MAX]  # a faked header can't make a huge Redis key
    client = scope.get("client")  # the direct peer when no proxy is in front
    return client[0] if client else "unknown"
