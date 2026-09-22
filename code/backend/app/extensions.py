"""Flask extensions, created here so every module imports the same instance.

They're built without an app and bound to one in `create_app()`, which is what keeps
the models importable from tests and CLI commands without circular imports.
"""

from flask_login import LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
login_manager = LoginManager()

# Schema changes as versioned files under migrations/versions/, applied with
# `flask db upgrade`. This supersedes decision D3 ("no migrations yet"): D3 was fine
# while nothing was deployed, but `db.create_all()` only ever creates missing tables --
# it will not add a column to an existing one, so the first schema change after a real
# deploy would need hand-written SQL against live data.
migrate = Migrate()

# Left at the default "basic" on purpose. "strong" ties the session to the client's IP,
# and in this setup one browser reaches Flask by two different routes — through the Vite
# proxy on :3000 and directly on :5001 — which share a cookie jar but not an IP. That
# logs you out mid-development for no security we actually need here.
login_manager.session_protection = "basic"
