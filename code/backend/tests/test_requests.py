"""The ID, access line, error line and metric each request leaves behind."""

import logging

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.errors import register_error_handlers
from app.core.requests import REQUEST_ID_HEADER, UNMATCHED, RequestMiddleware

logger = logging.getLogger("app.test")


@pytest.fixture
def small_app():
    """The middleware and error handlers on their own, with routes that can fail."""
    app = FastAPI()
    app.add_middleware(RequestMiddleware)
    register_error_handlers(app)

    @app.get("/api/things/{thing_id}")
    async def thing(thing_id: int) -> dict[str, int]:
        logger.info("looking")
        return {"id": thing_id}

    @app.get("/api/broken")
    async def broken() -> None:
        raise RuntimeError("the learner's private text")

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


async def _get(app, path, **headers):
    # The error middleware re-raises after it answers, so the client mustn't raise it too.
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path, headers=headers)


def _access_lines(caplog):
    return [record for record in caplog.records if record.name == "app.access"]


async def test_each_request_gets_an_id_on_its_reply_and_its_lines(small_app, logged):
    response = await _get(small_app, "/api/things/7")

    request_id = response.headers[REQUEST_ID_HEADER]
    assert len(request_id) == 32
    [looking] = [record for record in logged.records if record.getMessage() == "looking"]
    assert looking.request_id == request_id


@pytest.mark.parametrize(
    ("incoming", "kept"), [("from-the-proxy.1", True), ("has spaces", False), ("x" * 65, False)]
)
async def test_an_incoming_id_is_kept_only_if_it_looks_like_one(small_app, incoming, kept):
    response = await _get(small_app, "/api/things/7", **{REQUEST_ID_HEADER: incoming})

    assert (response.headers[REQUEST_ID_HEADER] == incoming) is kept


async def test_a_request_logs_one_line_with_its_route_not_its_path(small_app, logged):
    await _get(small_app, "/api/things/7")

    [line] = _access_lines(logged)
    assert (line.method, line.route, line.status) == ("GET", "/api/things/{thing_id}", 200)
    assert line.levelno == logging.INFO
    assert isinstance(line.duration_ms, int)
    assert line.request_id


async def test_health_checks_log_quietly(small_app, logged):
    await _get(small_app, "/api/health")

    [line] = _access_lines(logged)
    assert line.levelno == logging.DEBUG


async def test_an_unhandled_error_is_logged_once_with_its_request(small_app, logged):
    response = await _get(small_app, "/api/broken")

    assert response.status_code == 500
    [error] = [record for record in logged.records if record.levelno == logging.ERROR]
    assert error.getMessage() == "unhandled error"
    assert error.error_type == "RuntimeError"
    assert "in broken" in error.stack
    assert error.request_id
    assert "private" not in logged.text
    [line] = _access_lines(logged)
    assert line.status == 500


def _duration_count(metric_value, route, status):
    return metric_value(
        "http.server.request.duration",
        **{"http.request.method": "GET", "http.route": route, "http.response.status_code": status},
    )


async def test_a_request_is_measured_by_its_route(small_app, metric_value):
    before = _duration_count(metric_value, "/api/things/{thing_id}", 200)

    await _get(small_app, "/api/things/7")

    assert _duration_count(metric_value, "/api/things/{thing_id}", 200) - before == 1


async def test_unmatched_paths_share_one_label(small_app, metric_value):
    before = _duration_count(metric_value, UNMATCHED, 404)

    await _get(small_app, "/api/nothing-here-1")
    await _get(small_app, "/api/nothing-here-2")

    assert _duration_count(metric_value, UNMATCHED, 404) - before == 2


async def test_health_checks_arent_measured(small_app, metric_value):
    before = _duration_count(metric_value, "/api/health", 200)

    await _get(small_app, "/api/health")

    assert _duration_count(metric_value, "/api/health", 200) == before
