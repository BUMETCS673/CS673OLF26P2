"""Errors services raise. `app.errors` maps each one to an HTTP response."""


class ServiceError(Exception):
    def __init__(self, message: str, field: str | None = None):
        super().__init__(message)
        self.message = message
        self.field = field


class BudgetExceeded(ServiceError):
    """A daily limit or the AI's own quota is used up."""


class NotAvailable(ServiceError):
    """The AI didn't answer, isn't set up, or is turned off."""


class Conflict(ServiceError):
    """The request doesn't fit the current state, such as a reply already in progress."""


class InvalidRequest(ServiceError):
    """The request can't be done, such as a message to a full chat."""
