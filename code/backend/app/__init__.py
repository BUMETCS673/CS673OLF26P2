"""The application factory.

    from app import create_app
    app = create_app()

Everything that needs the app — extensions, blueprints, error handlers, CLI commands —
gets attached here, and nowhere else.
"""

# B1: registering time_travel_command in _register_cli().
# AI Utilization: ~100% of that change
# AI Tools Used: Claude Code (Claude Opus 5.5)
# AI-Assisted Activities:
#   CLI command registration
# Human role: plan approval, code review, and hands-on testing by Miles Cameron.

# Iteration 3, Step 0a: registering ai_smoke_command, and ai_generations in init-db's message.
# AI Utilization: ~100% of that change
# AI Tools Used: Claude Code (Claude Opus 5.5)
# AI-Assisted Activities:
#   CLI command registration
# Human role: plan approval, code review, and hands-on testing by Miles Cameron.

# Iteration 3, B3: the app logger's level, so the generate route's log line reaches gunicorn.
# AI Utilization: ~100% of that change
# AI Tools Used: Claude Code (Claude Opus 5.5)
# AI-Assisted Activities:
#   Logging configuration
# Human role: plan review, code review, and CI verification by Duc Anh Nguyen.

import logging

import click
from flask import Flask
from flask.cli import with_appcontext
from flask_migrate import stamp

from app.config import Config
from app.errors import ApiError, register_error_handlers
from app.extensions import db, login_manager, migrate


def create_app(config_object: type = Config) -> Flask:
    app = Flask(__name__)  # app/config.py loads code/.env at import time
    app.config.from_object(config_object)
    # Without a level, Flask's logger drops info outside debug mode, and with it the
    # generate route's one line per request (rule 17).
    app.logger.setLevel(logging.INFO)

    # Flask 3 reads this off `app.json`, not the config -- a JSON_SORT_KEYS entry in
    # config.py is silently ignored. Off, so responses come back in the order the API
    # contract lists the fields rather than alphabetically.
    app.json.sort_keys = False

    db.init_app(app)
    # render_as_batch rewrites ALTER TABLE as create-copy-swap, which SQLite needs
    # because it can't drop or alter a column in place. Harmless on Postgres, and it
    # means a migration written here still applies to a SQLite database.
    migrate.init_app(app, db, render_as_batch=True)
    login_manager.init_app(app)

    _register_login_handlers()
    register_error_handlers(app)
    _register_blueprints(app)
    _register_cli(app)

    return app


def _register_login_handlers() -> None:
    from app.models import User

    @login_manager.user_loader
    def load_user(user_id: str):
        return db.session.get(User, int(user_id))

    @login_manager.unauthorized_handler
    def unauthorized():
        # This is an API: @login_required answers with the contract's 401 JSON rather
        # than redirecting to a login page that doesn't exist.
        return ApiError(401, "Authentication required.").to_response()


def _register_blueprints(app: Flask) -> None:
    from app.api import api_bp

    app.register_blueprint(api_bp, url_prefix="/api")


def _register_cli(app: Flask) -> None:
    from app.ai.cli import ai_smoke_command
    from app.seed import seed_command, time_travel_command

    app.cli.add_command(init_db_command)
    app.cli.add_command(seed_command)
    app.cli.add_command(time_travel_command)
    app.cli.add_command(ai_smoke_command)


@click.command("init-db")
@with_appcontext
def init_db_command():
    """Create the database tables directly, skipping migrations.

    A convenience for a throwaway local database: `docker compose down -v`, `up`, then
    this and `flask seed`. It is NOT how a deployed database is set up -- use
    `flask db upgrade` there, which is what Render runs on every deploy.

    The difference matters: create_all() only creates tables that are missing. It will
    not add a column to a table that already exists, so it cannot apply a schema change
    to a database that has data in it.
    """
    from app import models  # noqa: F401  (imported so SQLAlchemy sees every table)

    db.create_all()
    # Record that the schema is already at the latest revision. Without this, a later
    # `flask db upgrade` on this database would try to create the tables a second time
    # and fail, because Alembic would have no record of what has been applied.
    stamp()
    click.echo("Tables created: users, decks, cards, ai_generations (stamped at head).")
