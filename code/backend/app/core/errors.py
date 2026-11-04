"""One error shape for the whole API: {"error": {"code", "message", "field"?}}.

Services raise the errors below, which know nothing about HTTP. The handlers turn them, and
everything else that can go wrong, into a response.
"""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    422: "validation_error",
    429: "rate_limited",
    500: "internal_error",
    503: "ai_unavailable",
}


class AppError(Exception):
    """An expected failure. `field` names the input it's about, if there is one."""

    status = 500

    def __init__(self, message: str, field: str | None = None):
        super().__init__(message)
        self.message = message
        self.field = field


class Unauthorized(AppError):
    status = 401


class NotFound(AppError):
    """Also the answer for "exists, but isn't yours", because 403 would confirm it exists."""

    status = 404


class Conflict(AppError):
    status = 409


class InvalidRequest(AppError):
    status = 422


class BudgetExceeded(AppError):
    status = 429


class NotAvailable(AppError):
    status = 503


def _response(status: int, message: str, field: str | None = None, headers=None) -> JSONResponse:
    error = {"code": _CODES.get(status, "error"), "message": message}
    if field is not None:
        error["field"] = field
    return JSONResponse({"error": error}, status_code=status, headers=headers)


def _validation_message(error: dict, field: str) -> str:
    """Our wording for the cases the frontend shows, and Pydantic's for anything else."""
    if error["type"] in ("missing", "string_type", "string_too_short"):
        return f"{field} is required."
    if error["type"] == "string_too_long":
        return f"{field} must be at most {error['ctx']['max_length']} characters."
    return error["msg"].removeprefix("Value error, ")


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return _response(exc.status, exc.message, exc.field)

    @app.exception_handler(RequestValidationError)
    async def _invalid_request(_: Request, exc: RequestValidationError) -> JSONResponse:
        error = exc.errors()[0]
        location = error["loc"]
        # The body as a whole isn't usable, rather than one of its fields.
        if len(location) == 1 or error["type"] == "json_invalid":
            return _response(400, "Request body must be a JSON object.")
        field = str(location[-1])
        return _response(422, _validation_message(error, field), field)

    @app.exception_handler(HTTPException)
    async def _http_error(_: Request, exc: HTTPException) -> JSONResponse:
        return _response(exc.status_code, str(exc.detail), headers=exc.headers)

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception) -> JSONResponse:
        # RequestMiddleware has logged it already, with the request's ID.
        return _response(500, "Something went wrong.")
