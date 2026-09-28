"""Story 2 acceptance tests: serve a deck's due cards (Lab 3)."""

from datetime import timedelta

from app.models.base import iso, utcnow


def _login(make_user, login_as):
    user = make_user()
    login_as(user)
    return user


def _get_due(client, deck):
    response = client.get(f"/api/decks/{deck.id}/due")
    assert response.status_code == 200
    body = response.get_json()
    assert set(body) == {"learning", "review", "new"}
    return body


def test_signed_out_request_is_401(client):
    assert client.get("/api/decks/1/due").status_code == 401


def test_another_users_deck_is_404(client, make_user, login_as, make_deck):
    _login(make_user, login_as)
    other = make_user(email="other@example.com")
    deck = make_deck(other)
    assert client.get(f"/api/decks/{deck.id}/due").status_code == 404


def test_missing_deck_is_404(client, make_user, login_as):
    _login(make_user, login_as)
    assert client.get("/api/decks/9999/due").status_code == 404


def test_empty_deck_returns_three_empty_lists(client, make_user, login_as, make_deck):
    deck = make_deck(_login(make_user, login_as))
    assert _get_due(client, deck) == {"learning": [], "review": [], "new": []}


def test_each_state_is_grouped_with_relearning_under_learning(
    client, make_user, login_as, make_deck, make_card
):
    deck = make_deck(_login(make_user, login_as))
    due = utcnow() - timedelta(minutes=1)
    new = make_card(deck)
    learning = make_card(deck, state="learning", due_at=due)
    review = make_card(deck, state="review", due_at=due)
    relearning = make_card(deck, state="relearning", due_at=due)

    body = _get_due(client, deck)

    assert [c["id"] for c in body["learning"]] == [learning.id, relearning.id]
    assert [c["id"] for c in body["review"]] == [review.id]
    assert [c["id"] for c in body["new"]] == [new.id]


def test_due_reviews_are_most_overdue_first_and_future_reviews_are_excluded(
    client, make_user, login_as, make_deck, make_card
):
    deck = make_deck(_login(make_user, login_as))
    now = utcnow()
    yesterday = make_card(deck, state="review", due_at=now - timedelta(days=1))
    make_card(deck, state="review", due_at=now + timedelta(days=1))
    oldest = make_card(deck, state="review", due_at=now - timedelta(days=3))

    body = _get_due(client, deck)

    assert [c["id"] for c in body["review"]] == [oldest.id, yesterday.id]


def test_reviews_with_equal_due_times_are_ordered_by_id(
    client, make_user, login_as, make_deck, make_card
):
    deck = make_deck(_login(make_user, login_as))
    due = utcnow() - timedelta(minutes=1)
    first = make_card(deck, state="review", due_at=due)
    second = make_card(deck, state="review", due_at=due)

    body = _get_due(client, deck)

    assert [c["id"] for c in body["review"]] == [first.id, second.id]


def test_learning_includes_overdue_and_five_minutes_ahead_but_not_thirty(
    client, make_user, login_as, make_deck, make_card
):
    deck = make_deck(_login(make_user, login_as))
    now = utcnow()
    soon = make_card(deck, state="learning", due_at=now + timedelta(minutes=5))
    make_card(deck, state="learning", due_at=now + timedelta(minutes=30))
    overdue = make_card(deck, state="learning", due_at=now - timedelta(hours=1))

    body = _get_due(client, deck)

    assert [c["id"] for c in body["learning"]] == [overdue.id, soon.id]


def test_twenty_five_new_cards_returns_first_twenty_created(
    client, make_user, login_as, make_deck, make_card
):
    deck = make_deck(_login(make_user, login_as))
    ids = [make_card(deck).id for _ in range(25)]

    body = _get_due(client, deck)

    assert [c["id"] for c in body["new"]] == ids[:20]


def test_two_hundred_five_due_reviews_returns_two_hundred_most_overdue(
    client, make_user, login_as, make_deck, make_card
):
    deck = make_deck(_login(make_user, login_as))
    now = utcnow()
    ids = [
        make_card(deck, state="review", due_at=now - timedelta(days=days)).id
        for days in range(1, 206)
    ]

    body = _get_due(client, deck)

    assert [c["id"] for c in body["review"]] == list(reversed(ids))[:200]


def test_returned_cards_include_state_and_due_at(
    client, make_user, login_as, make_deck, make_card
):
    deck = make_deck(_login(make_user, login_as))
    due = utcnow() - timedelta(minutes=1)
    cards = [make_card(deck)] + [
        make_card(deck, state=state, due_at=due)
        for state in ("learning", "review", "relearning")
    ]
    expected = {card.id: (card.state, iso(card.due_at)) for card in cards}

    body = _get_due(client, deck)
    returned = [card for group in body.values() for card in group]

    # Assert membership first so an empty stub cannot pass this check vacuously.
    assert {card["id"] for card in returned} == set(expected)
    for card in returned:
        assert (card["state"], card["due_at"]) == expected[card["id"]]
