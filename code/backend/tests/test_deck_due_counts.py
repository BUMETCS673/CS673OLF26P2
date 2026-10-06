"""Due counts on decks (Iteration 2, chunk B2).

Every Deck the API returns carries `due_counts`: how many learning, review, and new cards
GET /api/decks/:id/due would serve at the same moment. One test per acceptance example
under B2 in code/plans/FINALIZE_ITERATION_2_PLAN.md.
"""

# AI Utilization: ~100% of this file's code
# AI Tools Used: Devin (Cognition AI)
# AI-Assisted Activities:
#   Unit test creation (from the plan's acceptance examples)
# Human role: acceptance examples (B2 in the plan), direction, and review by Nurzat Mukhamedali.

from datetime import timedelta

from sqlalchemy import event

from app.models.base import utcnow

ZERO = {"learning": 0, "review": 0, "new": 0}


def _login(make_user, login_as):
    user = make_user()
    login_as(user)
    return user


def _get_deck(client, deck):
    response = client.get(f"/api/decks/{deck.id}")
    assert response.status_code == 200
    return response.get_json()


def _one_of_each_state(deck, make_card):
    due = utcnow() - timedelta(minutes=1)
    make_card(deck)
    make_card(deck, state="learning", due_at=due)
    make_card(deck, state="review", due_at=due)
    make_card(deck, state="relearning", due_at=due)


def test_a_deck_with_no_cards_has_three_zeros(client, make_user, login_as, make_deck):
    deck = make_deck(_login(make_user, login_as))

    assert _get_deck(client, deck)["due_counts"] == ZERO


def test_one_card_in_each_state_counts_relearning_as_learning(
    client, make_user, login_as, make_deck, make_card
):
    deck = make_deck(_login(make_user, login_as))
    _one_of_each_state(deck, make_card)

    body = client.get("/api/decks").get_json()

    assert [d["due_counts"] for d in body] == [{"learning": 2, "review": 1, "new": 1}]


def test_a_review_due_tomorrow_and_learning_due_in_thirty_minutes_are_not_counted(
    client, make_user, login_as, make_deck, make_card
):
    deck = make_deck(_login(make_user, login_as))
    now = utcnow()
    make_card(deck, state="review", due_at=now + timedelta(days=1))
    make_card(deck, state="learning", due_at=now + timedelta(minutes=30))

    assert _get_deck(client, deck)["due_counts"] == ZERO


def test_a_learning_card_due_in_fifteen_minutes_is_counted(
    client, make_user, login_as, make_deck, make_card
):
    deck = make_deck(_login(make_user, login_as))
    make_card(deck, state="learning", due_at=utcnow() + timedelta(minutes=15))

    assert _get_deck(client, deck)["due_counts"] == {"learning": 1, "review": 0, "new": 0}


def _over_the_caps(deck, make_card):
    now = utcnow()
    for _ in range(25):
        make_card(deck)
    for days in range(1, 206):
        make_card(deck, state="review", due_at=now - timedelta(days=days))


def test_new_and_review_are_capped_at_the_session_limits(
    client, make_user, login_as, make_deck, make_card
):
    deck = make_deck(_login(make_user, login_as))
    _over_the_caps(deck, make_card)

    assert _get_deck(client, deck)["due_counts"] == {"learning": 0, "review": 200, "new": 20}


def test_the_counts_equal_the_lists_due_serves(client, make_user, login_as, make_deck, make_card):
    user = _login(make_user, login_as)
    now = utcnow()
    empty = make_deck(user, name="Empty")
    each_state = make_deck(user, name="Each state")
    _one_of_each_state(each_state, make_card)
    not_yet = make_deck(user, name="Not yet")
    make_card(not_yet, state="review", due_at=now + timedelta(days=1))
    make_card(not_yet, state="learning", due_at=now + timedelta(minutes=30))
    ahead = make_deck(user, name="Learn ahead")
    make_card(ahead, state="learning", due_at=now + timedelta(minutes=15))
    capped = make_deck(user, name="Capped")
    _over_the_caps(capped, make_card)

    for deck in (empty, each_state, not_yet, ahead, capped):
        counts = _get_deck(client, deck)["due_counts"]
        due = client.get(f"/api/decks/{deck.id}/due").get_json()
        assert counts == {k: len(due[k]) for k in ("learning", "review", "new")}, deck.name


def test_creating_and_renaming_a_deck_both_return_due_counts(client, make_user, login_as):
    _login(make_user, login_as)

    created = client.post("/api/decks", json={"name": "Verbs"})
    assert created.status_code == 201
    assert created.get_json()["due_counts"] == ZERO

    renamed = client.patch(
        f"/api/decks/{created.get_json()['id']}", json={"name": "Irregular verbs"}
    )
    assert renamed.status_code == 200
    assert renamed.get_json()["due_counts"] == ZERO


def _statements_for(client, db, path):
    statements = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(db.engine, "before_cursor_execute", record)
    try:
        assert client.get(path).status_code == 200
    finally:
        event.remove(db.engine, "before_cursor_execute", record)
    return statements


def test_listing_five_decks_takes_as_many_queries_as_one(
    client, db, make_user, login_as, make_deck, make_card
):
    user = _login(make_user, login_as)
    first = make_deck(user, name="Deck 0")
    _one_of_each_state(first, make_card)
    db.session.expire_all()
    with_one = _statements_for(client, db, "/api/decks")

    for i in range(1, 5):
        _one_of_each_state(make_deck(user, name=f"Deck {i}"), make_card)
    db.session.expire_all()
    with_five = _statements_for(client, db, "/api/decks")

    assert len(client.get("/api/decks").get_json()) == 5
    assert len(with_five) == len(with_one), with_five


def test_another_users_due_cards_are_never_counted(
    client, make_user, login_as, make_deck, make_card
):
    mine = make_deck(_login(make_user, login_as))
    other = make_user(email="other@example.com")
    _one_of_each_state(make_deck(other, name="Theirs"), make_card)

    body = client.get("/api/decks").get_json()

    assert [(d["id"], d["due_counts"]) for d in body] == [(mine.id, ZERO)]
