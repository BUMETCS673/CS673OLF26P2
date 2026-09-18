"""Auth endpoints — WS1 (Miles).

The blueprint is registered by `app/api/__init__.py`; add routes here and they appear
under /api/auth. Endpoints to build, from the API contract:

    POST   /api/auth/register  {email, password, display_name?}  -> 201 User
    POST   /api/auth/login     {email, password}                 -> 200 User
    POST   /api/auth/logout                                      -> 204
    GET    /api/auth/me                                          -> 200 User | 401

Things WS0 left ready for you:
  - `User.normalize_email`, `set_password`, `check_password`, `to_dict` in app/models/user.py
  - `login_manager` already configured; @login_required returns the contract's 401 JSON
  - error helpers in app/errors.py: `raise conflict("Email already registered.")`
"""

from flask import Blueprint

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")

# TODO(WS1): the four endpoints above.
