"""Searching a user's chunks. Postgres only, because SQLite has no vector type."""

import pytest
from ai_fakes import ScriptedJudge, ToolWriter, search_for

from app.ai.fake import FakeProvider
from app.ai.provider import EMBEDDING_DIMENSIONS, AIRateLimited
from app.models import Document, DocumentChunk, User
from app.models.document import READY
from app.services import generation
from app.services.materials import MIN_SIMILARITY, search_chunks


@pytest.fixture(autouse=True)
def needs_postgres(db):
    if db.engine.dialect.name != "postgresql":
        pytest.skip("SQLite has no vector type")


def _towards(first, second=0.0):
    """A vector mostly along one axis, so that tests can set how close two vectors are."""
    vector = [0.0] * EMBEDDING_DIMENSIONS
    vector[0], vector[1] = first, second
    return vector


class Embedder(FakeProvider):
    """Every query points along the first axis."""

    def _embed(self, texts, is_query):
        return [_towards(1.0) for _ in texts]


@pytest.fixture
def add_document(db, make_user):
    made = {}

    def _add(email="me@example.com", content_hash="a", model="fake"):
        user = made.get(email) or make_user(email=email)
        made[email] = user
        document = Document(
            user_id=user.id, filename="notes.pdf", content_hash=content_hash * 64,
            embedding_model=model,
        )
        db.session.add(document)
        db.session.commit()
        return document

    return _add


def _add_chunk(db, document, text, vector, index=0, page=None):
    db.session.add(DocumentChunk(
        document_id=document.id, chunk_index=index, page=page, text=text, embedding=vector,
        embedding_model=document.embedding_model,
    ))
    db.session.commit()


def _search(**kwargs):
    return search_chunks(Embedder(), "cells", **kwargs)


def test_the_closest_chunks_come_first_with_their_details(db, add_document):
    document = add_document()
    _add_chunk(db, document, "further", _towards(1.0, 0.5), index=0, page=2)
    _add_chunk(db, document, "closest", _towards(1.0), index=1, page=9)

    found = _search()

    assert [chunk.text for chunk in found] == ["closest", "further"]
    assert found[0].page == 9
    assert found[0].similarity == pytest.approx(1.0)
    assert found[1].similarity < 1.0


def test_a_chunk_too_far_away_is_left_out(db, add_document):
    document = add_document()
    _add_chunk(db, document, "unrelated", _towards(0.0, 1.0))
    assert 0.0 < MIN_SIMILARITY

    assert _search() == []


def test_the_limit_keeps_the_best(db, add_document):
    document = add_document()
    _add_chunk(db, document, "second", _towards(1.0, 0.1), index=0)
    _add_chunk(db, document, "first", _towards(1.0), index=1)
    _add_chunk(db, document, "third", _towards(1.0, 0.2), index=2)

    assert [chunk.text for chunk in _search(limit=2)] == ["first", "second"]


def test_the_search_covers_every_users_files_and_accepted_cards(db, add_document):
    _add_chunk(db, add_document(), "my notes", _towards(1.0))
    _add_chunk(db, add_document(email="other@example.com"), "their notes", _towards(1.0, 0.1))
    db.session.add(DocumentChunk(
        text="What divides? Cells", embedding=_towards(1.0, 0.2), embedding_model="fake",
    ))
    db.session.commit()

    found = [chunk.text for chunk in _search()]

    assert found == ["my notes", "their notes", "What divides? Cells"]


def test_a_document_id_narrows_the_search(db, add_document):
    chosen = add_document(content_hash="a")
    other = add_document(content_hash="b")
    _add_chunk(db, chosen, "chosen", _towards(1.0, 0.5))
    _add_chunk(db, other, "other", _towards(1.0))
    db.session.add(DocumentChunk(
        text="a card", embedding=_towards(1.0), embedding_model="fake",
    ))
    db.session.commit()

    assert [chunk.text for chunk in _search(document_id=chosen.id)] == ["chosen"]
    assert {chunk.text for chunk in _search()} == {"chosen", "other", "a card"}


def test_the_same_passage_from_two_users_is_returned_once(db, add_document):
    _add_chunk(db, add_document(), "same page", _towards(1.0))
    _add_chunk(db, add_document(email="other@example.com"), "same page", _towards(1.0))
    _add_chunk(db, add_document(email="third@example.com"), "another page", _towards(1.0, 0.1))

    assert [chunk.text for chunk in _search(limit=2)] == ["same page", "another page"]


def test_vectors_from_another_model_are_left_out(db, add_document):
    older = add_document(model="an-older-model")
    _add_chunk(db, older, "old", _towards(1.0))

    assert _search() == []


def test_the_query_is_embedded_as_a_query(db, add_document):
    seen = []

    class Recording(Embedder):
        def _embed(self, texts, is_query):
            seen.append((texts, is_query))
            return super()._embed(texts, is_query)

    search_chunks(Recording(), "cells")

    assert seen == [(["cells"], True)]


def _generate_from(client, make_deck, user, document):
    deck = make_deck(user)
    return client.post(f"/api/decks/{deck.id}/generate", json={
        "mode": "file", "count": 1, "document_id": document.id, "topic": "Mitosis",
    })


def test_the_route_generates_from_real_vectors(
    client, db, add_document, make_deck, login_as
):
    document = add_document()
    document.status = READY
    db.session.commit()
    user = db.session.get(User, document.user_id)
    login_as(user)
    vector = FakeProvider().embed(["Mitosis"])[0]
    _add_chunk(db, document, "Cells divide by mitosis.", vector)

    resp = _generate_from(client, make_deck, user, document)

    assert resp.status_code == 201
    assert resp.get_json()["cards"]


def test_the_route_refuses_a_topic_real_vectors_dont_match(
    client, db, add_document, make_deck, login_as
):
    document = add_document()
    document.status = READY
    db.session.commit()
    user = db.session.get(User, document.user_id)
    login_as(user)
    opposite = [-number for number in FakeProvider().embed(["Mitosis"])[0]]
    _add_chunk(db, document, "Unrelated text.", opposite)

    resp = _generate_from(client, make_deck, user, document)

    assert resp.status_code == 422
    assert resp.get_json()["error"]["field"] == "topic"


def test_the_writers_tool_searches_real_vectors_from_inside_the_graph(
    client, db, add_document, make_deck, login_as, monkeypatch
):
    document = add_document()
    document.status = READY
    db.session.commit()
    user = db.session.get(User, document.user_id)
    login_as(user)
    _add_chunk(db, document, "Cells divide by mitosis.", _towards(1.0))
    writer = ToolWriter(search_for("cell cycle"), [{"front": "What divides?", "back": "Cells"}])
    judge = ScriptedJudge([{"index": 0, "ok": True}])
    embedder = Embedder()

    def providers(role="writer"):
        return {"judge": judge, "embedder": embedder}.get(role, writer)

    monkeypatch.setattr(generation, "get_provider", providers)

    resp = client.post(f"/api/decks/{make_deck(user).id}/generate", json={
        "mode": "prompt", "count": 1, "prompt": "Mitosis",
    })

    assert resp.status_code == 201
    assert "Cells divide by mitosis." in writer.prompts[0].text
    assert "<reference>\nCells divide by mitosis.\n</reference>" in judge.prompts[0].text


def test_a_query_that_cant_be_embedded_raises(db):
    with pytest.raises(AIRateLimited):
        search_chunks(FakeProvider(fail_with=AIRateLimited), "cells")
