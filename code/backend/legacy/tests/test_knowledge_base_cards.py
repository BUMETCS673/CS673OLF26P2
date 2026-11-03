"""Accepted cards go into the same knowledge base as file chunks."""

import pytest

from app.ai.fake import FakeProvider
from app.ai.provider import AIUnavailable
from app.models import AiGeneration, AiUsage, Card, DocumentChunk
from app.services import materials

CANDIDATES = [
    {"front": "What divides?", "back": "Cells", "status": "pending"},
    {"front": "What stores energy?", "back": "ATP", "status": "pending"},
]


@pytest.fixture
def me(make_user, login_as):
    user = make_user(email="me@example.com")
    login_as(user)
    return user


@pytest.fixture
def generation(db, me, make_deck):
    return _generation(db, me, make_deck(me))


def _generation(db, user, deck, candidates=None):
    row = AiGeneration(
        user_id=user.id, deck_id=deck.id, mode="prompt", requested_count=2, model="fake",
        candidates=[dict(candidate) for candidate in candidates or CANDIDATES],
    )
    db.session.add(row)
    db.session.commit()
    return row


def _accept(client, generation, indexes=(0,)):
    return client.post(
        f"/api/generations/{generation.id}/accept", json={"indexes": list(indexes)}
    )


def test_an_accepted_card_is_saved_like_any_other_chunk(client, generation):
    assert _accept(client, generation).status_code == 201

    saved = DocumentChunk.query.one()
    assert saved.text == "What divides? Cells"
    assert saved.document_id is None
    assert saved.source_card_id == Card.query.one().id
    assert saved.embedding_model == "fake"
    assert len(list(saved.embedding)) > 0


def test_cards_accepted_together_share_one_embedding_call(client, me, generation):
    _accept(client, generation, indexes=(0, 1))

    assert DocumentChunk.query.count() == 2
    usage = AiUsage.query.one()
    assert (usage.feature, usage.role, usage.calls, usage.user_id) == (
        "materials", "embedder", 1, me.id,
    )


def test_rejecting_a_card_adds_nothing(client, generation):
    client.post(f"/api/generations/{generation.id}/reject", json={"indexes": [0]})

    assert DocumentChunk.query.count() == 0


def test_a_failed_embedding_doesnt_stop_the_card_being_accepted(client, generation, monkeypatch):
    monkeypatch.setattr(
        materials, "get_provider", lambda role: FakeProvider(fail_with=AIUnavailable)
    )

    resp = _accept(client, generation)

    assert resp.status_code == 201
    assert resp.get_json()["cards"][0]["front"] == "What divides?"
    assert Card.query.count() == 1
    assert DocumentChunk.query.count() == 0


def test_accepting_works_without_an_embedder_set_up(client, app, generation):
    app.config["AI_EMBEDDER_PROVIDER"] = "not-a-vendor"

    assert _accept(client, generation).status_code == 201
    assert DocumentChunk.query.count() == 0


def test_accepting_works_when_the_model_limit_is_used_up(client, app, generation):
    app.config["AI_MODEL_DAILY_LIMIT"] = 0

    assert _accept(client, generation).status_code == 201
    assert Card.query.count() == 1
    assert DocumentChunk.query.count() == 0


def test_the_same_fact_from_two_users_is_only_kept_once(
    client, db, generation, make_user, make_deck, login_as
):
    if db.engine.dialect.name != "postgresql":
        pytest.skip("SQLite has no vectors to compare")
    _accept(client, generation)
    other = make_user(email="other@example.com")
    login_as(other)

    _accept(client, _generation(db, other, make_deck(other)))

    assert DocumentChunk.query.count() == 1
    assert Card.query.count() == 2


def test_a_different_fact_is_kept_too(client, db, generation):
    if db.engine.dialect.name != "postgresql":
        pytest.skip("SQLite has no vectors to compare")

    _accept(client, generation, indexes=(0, 1))

    assert DocumentChunk.query.count() == 2
