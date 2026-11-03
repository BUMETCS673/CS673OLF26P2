"""The demo data, and the commands that run it."""

from datetime import timedelta

import pytest
from sqlalchemy import select
from typer.testing import CliRunner

from app.cli import cli
from app.core.errors import NotFound
from app.models import Card, Deck, User, utcnow
from app.repositories.cards import CardRepository
from app.repositories.decks import DeckRepository
from app.repositories.users import UserRepository
from app.services.demo import DEMO_EMAIL, DemoService


@pytest.fixture
def service(session):
    return DemoService(
        session, UserRepository(session), DeckRepository(session), CardRepository(session)
    )


async def _demo_user(session) -> User:
    return await session.scalar(select(User).where(User.email == DEMO_EMAIL))


async def test_seeding_creates_two_decks_in_order(service, session):
    seeded = await service.seed()

    assert [(deck.name, deck.card_count) for deck in seeded] == [
        ("Spanish 101", 4),
        ("Travel Spanish", 11),
    ]
    decks = (await session.scalars(select(Deck).order_by(Deck.id))).all()
    assert [deck.id for deck in decks] == [deck.id for deck in seeded]


async def test_the_demo_password_works(service, client):
    await service.seed()

    resp = await client.post(
        "/api/auth/login", json={"email": DEMO_EMAIL, "password": "demo1234"}
    )

    assert resp.status_code == 200


async def test_travel_spanish_serves_three_cards_from_each_list(
    service, session, client, login_as
):
    seeded = await service.seed()
    await login_as(await _demo_user(session))

    body = (await client.get(f"/api/decks/{seeded[1].id}/due")).json()

    assert [len(body[name]) for name in ("review", "learning", "new")] == [3, 3, 3]


async def test_seeding_again_changes_nothing(service, session):
    await service.seed()
    before = (await _demo_user(session)).id

    assert await service.seed() is None

    assert (await _demo_user(session)).id == before


async def test_reset_starts_over_with_one_demo_user(service, session):
    await service.seed()
    old_id = (await _demo_user(session)).id

    seeded = await service.seed(reset=True)

    session.expunge_all()
    users = (await session.scalars(select(User).where(User.email == DEMO_EMAIL))).all()
    assert len(users) == 1
    assert users[0].id != old_id
    assert len(seeded) == 2


async def test_time_travel_only_moves_that_users_due_cards(
    service, session, me, make_deck, make_card
):
    seeded = await service.seed()
    other = await make_card(await make_deck(me), state="review", due_at=utcnow())
    other_due = other.due_at
    cards = select(Card).where(Card.deck_id == seeded[1].id, Card.front == "the hotel")
    hotel_due = (await session.scalar(cards)).due_at

    email, moved = await service.time_travel(2)

    session.expunge_all()
    assert (email, moved) == (DEMO_EMAIL, 8)
    assert (await session.scalar(cards)).due_at == hotel_due - timedelta(days=2)
    assert (await session.get(Card, other.id)).due_at == other_due
    new_card = select(Card).where(Card.deck_id == seeded[1].id, Card.front == "goodbye")
    assert (await session.scalar(new_card)).due_at is None


async def test_time_travel_for_an_unknown_email_says_so(service):
    with pytest.raises(NotFound, match="nobody@example.com"):
        await service.time_travel(1, "nobody@example.com")


def test_time_travel_needs_at_least_one_day():
    result = CliRunner().invoke(cli, ["time-travel", "--days", "0"])

    assert result.exit_code != 0
