"""One error shape for the whole API.

Every failure — raised by us, raised by Flask, or an unhandled crash — comes back as:

    { "error": { "code": "not_found", "message": "Deck not found" } }

so the frontend only ever has to handle one thing. Raise `ApiError` (or one of the
helpers below) from a route and the handler does the rest:

    from app.errors import ApiError, not_found, validation_error

    raise not_found("Deck not found")
    raise validation_error("name is required", field="name")
"""

from flask import jsonify
from werkzeug.exceptions import HTTPException

# Status code -> the `code` string in the contract.
STATUS_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    422: "validation_error",
    500: "internal_error",
}


class ApiError(Exception):
    """An error we're choosing to return. `field` is optional and only used by 422."""

    def __init__(self, status: int, message: str, code: str | None = None, field: str | None = None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.code = code or STATUS_CODES.get(status, "error")
        self.field = field

    def to_response(self):
        body = {"error": {"code": self.code, "message": self.message}}
        if self.field is not None:
            body["error"]["field"] = self.field
        return jsonify(body), self.status


def bad_request(message: str = "Request body must be valid JSON.") -> ApiError:
    return ApiError(400, message)


def unauthorized(message: str = "Authentication required.") -> ApiError:
    return ApiError(401, message)


def not_found(message: str = "Not found.") -> ApiError:
    """Also the right answer for "exists, but isn't yours" — see Security basics #3.

    404 rather than 403, because 403 confirms the thing exists.
    """
    return ApiError(404, message)


def conflict(message: str = "Already exists.") -> ApiError:
    return ApiError(409, message)


def validation_error(message: str, field: str | None = None) -> ApiError:
    return ApiError(422, message, field=field)


def register_error_handlers(app) -> None:
    @app.errorhandler(ApiError)
    def _handle_api_error(exc: ApiError):
        return exc.to_response()

    @app.errorhandler(HTTPException)
    def _handle_http_exception(exc: HTTPException):
        # Covers Flask's own aborts: 404 on an unknown URL, 405, malformed JSON, etc.
        status = exc.code or 500
        code = STATUS_CODES.get(status, "error")
        return ApiError(status, exc.description or code, code=code).to_response()

    @app.errorhandler(Exception)
    def _handle_unexpected(exc: Exception):
        if app.debug:
            # In `flask run --debug`, let it through so you get the real traceback in
            # the browser instead of a 500 that tells you nothing.
            raise exc
        # Otherwise: log the real reason for us, and tell the caller nothing that
        # would help an attacker.
        app.logger.exception("Unhandled error: %s", exc)
        return ApiError(500, "Something went wrong.").to_response()
