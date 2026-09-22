"""`flask seed` — a demo user with a deck and a few cards.

    demo@cadence.local / demo1234

Something to log into before auth exists, and something on the deck list before WS2's
endpoints do. Safe to run twice: if the demo user is already there it does nothing.
Run `flask init-db` first.
"""

import click
from flask.cli import with_appcontext

from app.extensions import db
from app.models import Card, Deck, User

DEMO_EMAIL = "demo@cadence.local"
DEMO_PASSWORD = "demo1234"

DEMO_CARDS = [
    ("la biblioteca", "the library"),
    ("el cuaderno", "the notebook"),
    ("aprender", "to learn"),
    ("la semana", "the week"),
]


@click.command("seed")
@with_appcontext
def seed_command():
    """Insert the demo user, deck, and cards."""
    existing = User.query.filter_by(email=DEMO_EMAIL).first()
    if existing is not None:
        click.echo(f"{DEMO_EMAIL} already exists — nothing to do.")
        return

    user = User(email=DEMO_EMAIL, display_name="Demo User")
    user.set_password(DEMO_PASSWORD)  # hashed, never stored as typed

    deck = Deck(
        user=user,
        name="Spanish 101",
        description="Core vocabulary",
        cards=[Card(front=front, back=back) for front, back in DEMO_CARDS],
    )

    db.session.add(deck)
    db.session.commit()

    click.echo(
        f"Seeded {DEMO_EMAIL} (password: {DEMO_PASSWORD}) "
        f"with deck {deck.name!r} and {len(DEMO_CARDS)} cards."
    )
