"""`flask seed` — a demo user with two decks.

    demo@cadence.local / demo1234

"Spanish 101" is four new cards, unchanged since Iteration 1. "Travel Spanish" has a card
at every stage of Anki's cycle, so a demo can show reviews, a relapse, and learning cards
without waiting days for them (B1 in code/plans/FINALIZE_ITERATION_2_PLAN.md).

Safe to run twice: if the demo user is already there it does nothing, unless you pass
--reset. Run `flask db upgrade` first (or `flask init-db` for a throwaway database).

`flask time-travel --days N` makes N days pass for one user's cards, for showing a card
come back after it graduates.
"""

# AI Utilization: ~100% of this file's code
# AI Tools Used: Claude Code (Claude Opus 5.5; Iteration 1's version, Claude Opus 5)
# AI-Assisted Activities:
#   Demo data and CLI command development
#   Documentation
# Human role: plan approval, code review, and hands-on testing by Miles Cameron.

from datetime import datetime, timedelta

import click
from flask.cli import with_appcontext

from app.extensions import db
from app.models import Card, Deck, User, as_utc, utcnow
from app.scheduler import STARTING_EASE, CardSchedule, CardState

DEMO_EMAIL = "demo@cadence.local"
DEMO_PASSWORD = "demo1234"

DEMO_CARDS = [
    ("la biblioteca", "the library"),
    ("el cuaderno", "the notebook"),
    ("aprender", "to learn"),
    ("la semana", "the week"),
]

TRAVEL_DECK_NAME = "Travel Spanish"
TRAVEL_DECK_DESCRIPTION = "English → Spanish, with cards at every stage"


def _travel_cards(now: datetime) -> list[Card]:
    """Travel Spanish's cards, with every due time relative to `now`.

    Right after seeding, GET /api/decks/<id>/due serves the first three under `review`,
    the next three under `learning` (the ticket because it's within the 20-minute
    learn-ahead window), and the last three under `new`. The hotel and the map aren't due.
    """

    def card(front, back, state=CardState.NEW, due_in=None, interval_days=0,
             ease_factor=STARTING_EASE, step=0, lapses=0):
        made = Card(front=front, back=back)
        made.schedule = CardSchedule(
            state=state,
            due_at=None if due_in is None else now + due_in,
            interval_days=interval_days,
            ease_factor=ease_factor,
            step=step,
            lapses=lapses,
        )
        return made

    review, learning, relearning = CardState.REVIEW, CardState.LEARNING, CardState.RELEARNING
    return [
        # Story 1's "4 days overdue" example: Hard 12d, Good 30d, Easy 46d.
        card("the airport", "el aeropuerto", review, -timedelta(days=4), interval_days=10),
        card("the train station", "la estación de tren", review, -timedelta(days=1), interval_days=4),
        # On time with a 1-day interval, so the minimums decide: 2d, 3d, 4d.
        card("the beach", "la playa", review, -timedelta(hours=1), interval_days=1),
        # Failed from review 5 minutes ago: ease and lapses already took the hit.
        card("the passport", "el pasaporte", relearning, -timedelta(minutes=5),
             interval_days=1, ease_factor=2300, lapses=1),
        card("the suitcase", "la maleta", learning, -timedelta(minutes=2), step=1),
        card("the ticket", "el boleto", learning, timedelta(minutes=8), step=1),
        card("the hotel", "el hotel", review, timedelta(days=5), interval_days=12),
        card("the map", "el mapa", review, timedelta(days=30), interval_days=40),
        card("goodbye", "adiós"),
        card("the library", "la biblioteca"),
        card("the song", "la canción"),
    ]


@click.command("seed")
@click.option(
    "--reset",
    is_flag=True,
    help="Delete the demo user and everything they own first, then seed again.",
)
@with_appcontext
def seed_command(reset):
    """Insert the demo user and their two decks."""
    existing = User.query.filter_by(email=DEMO_EMAIL).first()
    if existing is not None:
        if not reset:
            click.echo(f"{DEMO_EMAIL} already exists — nothing to do. Use --reset to start over.")
            return
        # The database cascades this to their decks and cards. Flush it before adding the
        # new user, or the unique email would collide inside the same flush. The cascade
        # happens behind the session's back, so drop anything it still holds for those rows.
        db.session.delete(existing)
        db.session.flush()
        db.session.expunge_all()

    # One clock reading, so every due time in the deck is relative to the same moment.
    now = utcnow()
    user = User(email=DEMO_EMAIL, display_name="Demo User")
    user.set_password(DEMO_PASSWORD)  # hashed, never stored as typed

    spanish = Deck(
        user=user,
        name="Spanish 101",
        description="Core vocabulary",
        cards=[Card(front=front, back=back) for front, back in DEMO_CARDS],
    )
    travel = Deck(
        user=user,
        name=TRAVEL_DECK_NAME,
        description=TRAVEL_DECK_DESCRIPTION,
        cards=_travel_cards(now),
    )

    # Spanish 101 first, so on a fresh database it's still deck 1, as Lab 3's walk-through
    # expects.
    db.session.add(spanish)
    db.session.flush()
    db.session.add(travel)
    db.session.commit()

    # The ids, because they're only 1 and 2 on a fresh database: Postgres never reuses an
    # id, so every --reset gives the decks new ones, and the walkthrough needs to know them.
    click.echo(
        f"{'Reset' if existing else 'Seeded'} {DEMO_EMAIL} (password: {DEMO_PASSWORD}) with "
        f"{spanish.name!r} (id {spanish.id}, {len(spanish.cards)} cards) and "
        f"{travel.name!r} (id {travel.id}, {len(travel.cards)} cards)."
    )


@click.command("time-travel")
@click.option(
    "--days",
    type=click.IntRange(min=1),
    required=True,
    help="How many days to pretend have passed.",
)
@click.option(
    "--email",
    default=DEMO_EMAIL,
    show_default=True,
    help="Whose cards to move.",
)
@with_appcontext
def time_travel_command(days, email):
    """Make N days pass for one user's cards: every due time moves N days earlier.

    For demos: rate a card Good so it graduates to "1d", time-travel a day, and it's due
    again. Only that user's cards change, and new cards, which have no due time, don't.
    A CLI command only, never an HTTP route.
    """
    user = User.query.filter_by(email=User.normalize_email(email)).first()
    if user is None:
        raise click.ClickException(f"No user with the email {email}.")

    cards = (
        Card.query.join(Deck)
        .filter(Deck.user_id == user.id, Card.due_at.isnot(None))
        .all()
    )
    for card in cards:
        # as_utc: SQLite hands timestamps back without a timezone (rule 8, Lab 3 plan).
        card.due_at = as_utc(card.due_at) - timedelta(days=days)
    db.session.commit()

    click.echo(f"Moved {len(cards)} of {user.email}'s cards {days} day(s) earlier.")
