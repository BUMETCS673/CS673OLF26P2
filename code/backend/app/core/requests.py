"""What each request leaves behind: an ID on its log lines, one access line, and its metric."""

import logging
import re
import time
import traceback
from uuid import uuid4

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logs import log_fields
from app.core.telemetry import meter

REQUEST_ID_HEADER = "X-Request-ID"
# An incoming ID is kept only if it looks like one, so a client can't write into the logs.
_VALID_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")
# Render checks this every few seconds, which would bury every other request.
_QUIET_PATH = "/api/health"
# A path no route matched, like a scanner's guess, shares one label instead of making its own.
UNMATCHED = "unmatched"

REQUEST_DURATION = meter.create_histogram(
    # OpenTelemetry's standard name and attributes, so Grafana's HTTP dashboards read it as is.
    "http.server.request.duration",
    unit="s",
    description="How long the API took to answer, by method, route and status.",
    explicit_bucket_boundaries_advisory=[
        0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1, 2.5, 5, 7.5, 10, 30, 60
    ],
)
access_logger = logging.getLogger("app.access")
logger = logging.getLogger(__name__)


def _request_id(scope: Scope) -> str:
    for name, value in scope["headers"]:
        if name == b"x-request-id":
            incoming = value.decode("latin-1")
            if _VALID_REQUEST_ID.fullmatch(incoming):
                return incoming
    return uuid4().hex


class RequestMiddleware:
    """Gives each request an ID for its lines, and logs and measures it when it ends.

    It also logs an unhandled error, while the request's ID is still set. A plain ASGI
    middleware, so a streamed reply, like a job's live events, passes straight through.
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = _request_id(scope)
        status = 500  # what the client gets if the app fails before it answers
        started = time.perf_counter()

        async def send_with_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message.setdefault("headers", [])
                MutableHeaders(scope=message).append(REQUEST_ID_HEADER, request_id)
            await send(message)

        with log_fields(request_id=request_id):
            try:
                await self.app(scope, receive, send_with_id)
            except Exception as error:
                # Its type and where it happened, not its message, which can quote what the
                # learner sent.
                logger.error(
                    "unhandled error",
                    extra={
                        "error_type": type(error).__name__,
                        "stack": "".join(traceback.format_tb(error.__traceback__)),
                    },
                )
                raise
            finally:
                self._finish(scope, status, time.perf_counter() - started)

    @staticmethod
    def _finish(scope: Scope, status: int, seconds: float) -> None:
        # The route's template, like /api/decks/{deck_id}, so IDs don't split one route into
        # many. FastAPI's router sets it on the scope once a route matches.
        route = getattr(scope.get("route"), "path", None)
        quiet = route is not None and route.startswith(_QUIET_PATH)
        access_logger.log(
            logging.DEBUG if quiet else logging.INFO,
            "request",
            extra={
                "method": scope["method"],
                "route": route or scope["path"],
                "status": status,
                "duration_ms": round(seconds * 1000),
            },
        )
        if not quiet:
            REQUEST_DURATION.record(
                seconds,
                {
                    "http.request.method": scope["method"],
                    "http.route": route or UNMATCHED,
                    "http.response.status_code": status,
                },
            )
