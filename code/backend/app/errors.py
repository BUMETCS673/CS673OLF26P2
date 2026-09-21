"""One error shape for the whole API.

Every failure — raised by us, raised by Flask, or an unhandled crash — comes back as:

    { "error": { "code": "not_found", "message": "Deck not found" } }

so the frontend only ever has to handle one thing. Raise `ApiError` (or one of the
helpers below) from a route and the handler does the rest:

    from app.errors import ApiError, not_found, validation_error

    raise not_found("Deck not found")
    raise validation_error("name is required", field="name")

Any endpoint that takes a request body reads it with `json_object()` below, rather
than calling `request.get_json()` itself.
"""

from flask import jsonify, request
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

# Statuses Werkzeug raises that the contract has no code for. Rather than invent one
# the frontend doesn't handle, answer with the contract status these amount to.
# See D6 and D7 in ITERATION_1_PLAN.md.
REMAPPED_STATUS = {
    # A bare `get_json()` on a request with no JSON Content-Type. Endpoints using
    # `json_object()` never get here.
    415: (400, "Request body must be JSON. Set Content-Type: application/json."),
    # Body over MAX_CONTENT_LENGTH.
    413: (400, "Request body is too large."),
}


class ApiError(Exception):
    """An error we're choosing to return. `field` is optional and only used by 422."""

    def __init__(
        self,
        status: int,
        message: str,
        code: str | None = None,
        field: str | None = None,
    ):
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


def json_object() -> dict:
    """The request body as a dict, or the contract's 400.

    **Use this instead of `request.get_json()`** in every endpoint that takes a body.
    A bare `get_json()` raises 415 when the caller leaves off the `Content-Type:
    application/json` header, and 415 isn't one of the codes in the contract.
    """
    # silent: a parse failure is our 400, not an unhandled 500, and not a 415.
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise bad_request("Request body must be a JSON object.")
    return body


def register_error_handlers(app) -> None:
    @app.errorhandler(ApiError)
    def _handle_api_error(exc: ApiError):
        return exc.to_response()

    @app.errorhandler(HTTPException)
    def _handle_http_exception(exc: HTTPException):
        # Covers Flask's own aborts: 404 on an unknown URL, 405, malformed JSON, etc.
        status = exc.code or 500
        if status in REMAPPED_STATUS:
            status, message = REMAPPED_STATUS[status]
            return ApiError(status, message).to_response()
        code = STATUS_CODES.get(status, "error")
        response, _ = ApiError(status, exc.description or code, code=code).to_response()

        # Some of these carry headers the protocol requires -- Allow on a 405,
        # WWW-Authenticate on a 401. Replacing the body with JSON would throw them
        # away, so carry them over. Skip the content headers, which describe the
        # body we just replaced.
        for name, value in exc.get_headers():
            if name.lower() not in ("content-type", "content-length"):
                response.headers[name] = value

        return response, status

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
