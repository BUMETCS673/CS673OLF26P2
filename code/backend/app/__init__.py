"""The application factory.

    from app import create_app
    app = create_app()

Everything that needs the app — extensions, blueprints, error handlers, CLI commands —
gets attached here, and nowhere else.
"""

import click
from flask import Flask
from flask.cli import with_appcontext

from app.config import Config
from app.errors import ApiError, register_error_handlers
from app.extensions import db, login_manager


def create_app(config_object: type = Config) -> Flask:
    app = Flask(__name__)  # app/config.py loads code/.env at import time
    app.config.from_object(config_object)

    db.init_app(app)
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
    from app.seed import seed_command

    app.cli.add_command(init_db_command)
    app.cli.add_command(seed_command)


@click.command("init-db")
@with_appcontext
def init_db_command():
    """Create the database tables.

    No migrations this iteration (decision D3) — to start over, run
    `docker compose down -v`, then `up`, then this and `flask seed` again.
    """
    from app import models  # noqa: F401  (imported so SQLAlchemy sees every table)

    db.create_all()
    click.echo("Tables created: users, decks, cards.")
