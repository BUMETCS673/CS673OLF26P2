"""Flask extensions, created here so every module imports the same instance.

They're built without an app and bound to one in `create_app()`, which is what keeps
the models importable from tests and CLI commands without circular imports.
"""

from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
login_manager = LoginManager()

# Left at the default "basic" on purpose. "strong" ties the session to the client's IP,
# and in this setup one browser reaches Flask by two different routes — through the Vite
# proxy on :3000 and directly on :5001 — which share a cookie jar but not an IP. That
# logs you out mid-development for no security we actually need here.
login_manager.session_protection = "basic"
