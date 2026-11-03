"""File mode with a saved document: the topic finds the chunks the writer and judge get.

Search needs Postgres, so it's replaced here. test_materials_search.py covers the real one.
"""

import pytest
from ai_fakes import Scripted, ScriptedJudge, ToolWriter, search_for, spend, submit

from app.ai.provider import EMBEDDING_DIMENSIONS, AIRateLimited, AIUnavailable
from app.models import AiGeneration, AiUsage, Document, DocumentChunk
from app.models.document import PROCESSING, READY
from app.services import generation
from app.services.materials import FoundChunk

CARD = {"front": "What divides?", "back": "Cells"}
PASS = [{"index": 0, "ok": True}]


@pytest.fixture
def me(make_user, login_as):
    user = make_user(email="me@example.com")
    login_as(user)
    return user


@pytest.fixture
def deck(me, make_deck):
    return make_deck(me, name="Biology")


@pytest.fixture
def document(db, me):
    return _document(db, me)


def _document(db, user, status=READY):
    row = Document(
        user_id=user.id, filename="notes.pdf", content_hash="a" * 64, status=status,
    )
    db.session.add(row)
    db.session.commit()
    return row


@pytest.fixture
def searches(monkeypatch):
    """Replaces the search with one that finds a chunk, and records how it was asked."""
    asked = []
    results = [FoundChunk(1, 3, "Cells divide by mitosis.", 0.9)]

    def search(embedder, query, document_id=None, limit=None):
        asked.append({"query": query, "document_id": document_id, "limit": limit})
        return results

    monkeypatch.setattr(generation, "search_chunks", search)
    return asked, results


@pytest.fixture
def writer(monkeypatch):
    scripted = Scripted([CARD], [CARD])
    judge = ScriptedJudge(PASS)
    monkeypatch.setattr(
        generation, "get_provider",
        lambda role="writer": judge if role == "judge" else scripted,
    )
    return scripted, judge


def _post(client, deck, document_id, topic="Mitosis", count=1):
    return client.post(f"/api/decks/{deck.id}/generate", json={
        "mode": "file", "count": count, "document_id": document_id, "topic": topic,
    })


def test_the_topic_searches_only_that_document(client, deck, document, searches, writer):
    asked, _ = searches

    resp = _post(client, deck, document.id)

    assert resp.status_code == 201
    assert asked[0]["query"] == "Mitosis"
    assert asked[0]["document_id"] == document.id


def test_the_writer_gets_the_found_chunks_and_the_topic(client, deck, document, searches, writer):
    scripted, _ = writer

    _post(client, deck, document.id)

    text = scripted.prompts[0].text
    assert "Cells divide by mitosis." in text
    assert "<focus>\nMitosis\n</focus>" in text


def test_the_judge_checks_against_the_found_chunks(client, deck, document, searches, writer):
    _, judge = writer

    _post(client, deck, document.id)

    assert "<source>\nCells divide by mitosis.\n</source>" in judge.prompts[0].text
    assert "<topic>\nMitosis\n</topic>" in judge.prompts[0].text


def test_the_writer_is_told_to_stay_on_the_topic(client, deck, document, searches, writer):
    scripted, _ = writer

    _post(client, deck, document.id)

    assert "only about the topic in <focus>" in scripted.prompts[0].text


def test_an_off_topic_card_goes_to_repair_with_its_reason(
    client, deck, document, searches, writer
):
    scripted, judge = writer
    judge.verdicts = [{"index": 0, "ok": False, "reason": "It isn't about Mitosis."}]

    _post(client, deck, document.id)

    assert "It isn't about Mitosis." in scripted.prompts[1].text


def test_the_batch_records_the_topic_and_file(client, deck, document, searches, writer):
    _post(client, deck, document.id)

    row = AiGeneration.query.one()
    assert (row.mode, row.prompt, row.source_filename) == ("file", "Mitosis", "notes.pdf")


@pytest.mark.parametrize(("count", "limit"), [(1, 6), (5, 10), (25, 20)])
def test_more_cards_get_more_chunks_within_a_limit(
    client, deck, document, searches, writer, count, limit
):
    asked, _ = searches

    _post(client, deck, document.id, count=count)

    assert asked[0]["limit"] == limit


def test_a_topic_the_file_doesnt_cover_is_refused_without_a_writer_call(
    client, deck, document, searches, writer
):
    _, results = searches
    results.clear()
    scripted, _ = writer

    resp = _post(client, deck, document.id)

    assert resp.status_code == 422
    assert resp.get_json()["error"]["field"] == "topic"
    assert scripted.usage.calls == 0
    assert AiGeneration.query.count() == 0


@pytest.mark.parametrize(
    ("failure", "status"), [(AIRateLimited(), 429), (AIUnavailable(), 503)]
)
def test_a_search_that_fails_is_an_error_not_cards_from_nothing(
    client, deck, document, monkeypatch, writer, failure, status
):
    def search(*args, **kwargs):
        raise failure

    monkeypatch.setattr(generation, "search_chunks", search)
    scripted, _ = writer

    assert _post(client, deck, document.id).status_code == status
    assert scripted.usage.calls == 0


def test_a_topic_is_required(client, deck, document, searches, writer):
    resp = _post(client, deck, document.id, topic="   ")

    assert resp.status_code == 422
    assert resp.get_json()["error"]["field"] == "topic"


def test_a_topic_has_a_length_limit(client, deck, document, searches, writer):
    resp = _post(client, deck, document.id, topic="x" * 501)

    assert resp.status_code == 422


@pytest.mark.parametrize("document_id", ["7", None, True, 1.5])
def test_a_bad_document_id_is_refused(client, deck, document_id, writer):
    resp = _post(client, deck, document_id)

    assert resp.status_code == 422
    assert resp.get_json()["error"]["field"] == "document_id"


def test_a_missing_document_is_404(client, deck, writer):
    assert _post(client, deck, 999).status_code == 404


def test_another_users_document_looks_missing(client, db, deck, make_user, writer):
    theirs = _document(db, make_user(email="other@example.com"))

    assert _post(client, deck, theirs.id).status_code == 404


def test_a_document_still_processing_is_refused(client, db, me, deck, writer):
    waiting = _document(db, me, status=PROCESSING)

    resp = _post(client, deck, waiting.id)

    assert resp.status_code == 422
    assert resp.get_json()["error"]["field"] == "document_id"


def test_the_model_limit_includes_the_embedding_call(client, me, deck, document, searches):
    # Every role uses "fake" here: 5 for a full run, and 1 for the embedding, of 18.
    spend(me.id, 13)

    assert _post(client, deck, document.id).status_code == 429
    assert AiUsage.query.count() == 1  # only the row `spend` added


def test_the_same_spend_leaves_room_without_a_document(client, me, deck):
    spend(me.id, 13)

    resp = client.post(f"/api/decks/{deck.id}/generate", json={
        "mode": "prompt", "count": 1, "prompt": "Cells",
    })

    assert resp.status_code == 201


# --- prompt mode ---------------------------------------------------------------------------


def _add_to_knowledge_base(db, model="fake"):
    db.session.add(DocumentChunk(
        text="Cells divide.", embedding=[0.5] * EMBEDDING_DIMENSIONS, embedding_model=model,
    ))
    db.session.commit()


def _post_prompt(client, deck, count=1):
    return client.post(f"/api/decks/{deck.id}/generate", json={
        "mode": "prompt", "count": count, "prompt": "Mitosis",
    })


def _use_writer(monkeypatch, tool_writer, judge=None):
    judge = judge or ScriptedJudge(PASS)
    monkeypatch.setattr(
        generation, "get_provider",
        lambda role="writer": judge if role == "judge" else tool_writer,
    )
    return judge


def test_prompt_mode_searches_the_whole_knowledge_base(
    client, db, deck, searches, monkeypatch
):
    _add_to_knowledge_base(db)  # nothing from this user: it's shared
    tool_writer = ToolWriter(search_for("cell cycle"), [CARD])
    judge = _use_writer(monkeypatch, tool_writer)
    asked, _ = searches

    resp = _post_prompt(client, deck, count=5)

    assert resp.status_code == 201
    assert asked == [{"query": "cell cycle", "document_id": None, "limit": 10}]
    assert "<source>\nCells divide by mitosis.\n</source>" in tool_writer.prompts[0].text
    assert "<reference>\nCells divide by mitosis.\n</reference>" in judge.prompts[0].text


def test_prompt_mode_can_write_without_searching(client, db, deck, searches, monkeypatch):
    _add_to_knowledge_base(db)
    _use_writer(monkeypatch, ToolWriter(submit(CARD)))
    asked, _ = searches

    resp = _post_prompt(client, deck)

    assert resp.status_code == 201
    assert asked == []
    assert [card["front"] for card in resp.get_json()["cards"]] == ["What divides?"]


@pytest.mark.parametrize("setup", ["empty", "other_model", "embedder_not_set_up"])
def test_prompt_mode_has_no_tool_when_a_search_couldnt_find_anything(
    client, app, db, deck, monkeypatch, setup
):
    if setup == "other_model":
        _add_to_knowledge_base(db, model="an-older-model")
    elif setup == "embedder_not_set_up":
        _add_to_knowledge_base(db)
        app.config["AI_EMBEDDER_PROVIDER"] = "not-a-vendor"
    tool_writer = ToolWriter([CARD])
    _use_writer(monkeypatch, tool_writer)

    assert _post_prompt(client, deck).status_code == 201
    assert tool_writer.chats == []


def test_the_model_limit_reserves_room_for_a_search(client, db, me, deck):
    spend(me.id, 11)  # with search, a full run reserves 8 of the 18
    _add_to_knowledge_base(db)

    assert _post_prompt(client, deck).status_code == 429


def test_the_same_spend_is_fine_when_there_is_nothing_to_search(client, me, deck):
    spend(me.id, 11)  # without search, a full run reserves 5

    assert _post_prompt(client, deck).status_code == 201


def test_file_mode_needs_a_document(client, deck):
    resp = client.post(f"/api/decks/{deck.id}/generate", json={
        "mode": "file", "count": 1, "topic": "Mitosis",
    })

    assert resp.status_code == 422
    assert resp.get_json()["error"]["field"] == "document_id"


def test_an_inline_file_is_no_longer_accepted(client, deck):
    resp = client.post(f"/api/decks/{deck.id}/generate", json={
        "mode": "file", "count": 1,
        "file": {"name": "notes.txt", "mime_type": "text/plain", "data": "Q2VsbHMu"},
    })

    assert resp.status_code == 422
