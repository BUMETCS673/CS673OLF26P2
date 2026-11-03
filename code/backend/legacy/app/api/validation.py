"""Text checks shared by the routes that take a JSON body.

Each one raises the contract's 422 with `field` set, and the wording is the same
everywhere: "<field> is required.", "<field> must be text.", "<field> must be at most N
characters.". Callers switch on the code and field, never on the wording.
"""

# AI Utilization: ~100% of this file's code
# AI Tools Used: Claude Code (Claude Opus 5.5)
# AI-Assisted Activities:
#   Refactoring
# Human role: plan approval and code review by Duc Anh Nguyen.

from app.errors import validation_error


def required_text(value, field: str, max_length: int | None = None, *, strip: bool = True) -> str:
    """A non-empty string, stripped unless strip=False. Anything else is "required".

    strip=False is for passwords: spaces count, so "   " gets through here and is left
    to the password rules.
    """
    if not isinstance(value, str):
        raise validation_error(f"{field} is required.", field=field)
    if strip:
        value = value.strip()
    if not value:
        raise validation_error(f"{field} is required.", field=field)
    _check_length(value, field, max_length)
    return value


def optional_text(value, field: str, max_length: int, *, strip: bool = True) -> str | None:
    """None, or a string within max_length.

    With strip, the value is stripped and a blank one becomes None. With strip=False it
    is kept exactly as sent, blank included.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise validation_error(f"{field} must be text.", field=field)
    if strip:
        value = value.strip()
    _check_length(value, field, max_length)
    return (value or None) if strip else value


def _check_length(value: str, field: str, max_length: int | None) -> None:
    if max_length is not None and len(value) > max_length:
        raise validation_error(
            f"{field} must be at most {max_length} characters.", field=field
        )
