"""The documents table."""

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import EMBEDDING_DIMENSIONS, Card, Document, DocumentChunk
from app.models.document import PROCESSING, QUEUED

HASH = "a" * 64
VECTOR = [0.5] * EMBEDDING_DIMENSIONS


def _add(db, user, content_hash=HASH):
    db.session.add(Document(user_id=user.id, filename="notes.pdf", content_hash=content_hash))
    db.session.commit()


def test_a_new_document_starts_queued(db, make_user):
    _add(db, make_user())

    document = Document.query.one()
    assert (document.status, document.stage) == (PROCESSING, QUEUED)
    assert (document.chunks_total, document.chunks_done) == (0, 0)


def test_a_user_cant_store_the_same_file_twice(db, make_user):
    user = make_user()
    _add(db, user)

    with pytest.raises(IntegrityError):
        _add(db, user)
    db.session.rollback()


def test_two_users_can_store_the_same_file(db, make_user):
    _add(db, make_user(email="a@example.com"))
    _add(db, make_user(email="b@example.com"))

    assert Document.query.count() == 2


def _add_chunk(db, document, chunk_index=0):
    db.session.add(
        DocumentChunk(
            document_id=document.id, chunk_index=chunk_index, text="ATP", embedding=VECTOR,
            embedding_model="fake",
        )
    )
    db.session.commit()


def test_a_chunk_keeps_its_text_and_embedding(db, make_user):
    _add(db, make_user())

    _add_chunk(db, Document.query.one())

    chunk = DocumentChunk.query.one()
    assert chunk.text == "ATP"
    assert chunk.page is None
    assert list(chunk.embedding) == pytest.approx(VECTOR)


@pytest.fixture
def card(db, make_user, make_deck):
    row = Card(deck_id=make_deck(make_user()).id, front="What divides?", back="Cells")
    db.session.add(row)
    db.session.commit()
    return row


def _add_card_copy(db, card):
    db.session.add(DocumentChunk(
        source_card_id=card.id, text="What divides? Cells", embedding=VECTOR,
        embedding_model="fake",
    ))
    db.session.commit()


def test_an_accepted_cards_copy_needs_no_document(db, card):
    _add_card_copy(db, card)

    saved = DocumentChunk.query.one()
    assert (saved.document_id, saved.chunk_index) == (None, None)
    assert (saved.source_card_id, saved.embedding_model) == (card.id, "fake")


def test_a_card_is_only_copied_once(db, card):
    _add_card_copy(db, card)

    with pytest.raises(IntegrityError):
        _add_card_copy(db, card)
    db.session.rollback()


def test_the_copy_outlives_the_card(db, card):
    _add_card_copy(db, card)

    db.session.delete(card)
    db.session.commit()

    saved = DocumentChunk.query.one()
    assert saved.source_card_id is None
    assert saved.text == "What divides? Cells"


def test_a_document_cant_save_the_same_chunk_twice(db, make_user):
    _add(db, make_user())
    document = Document.query.one()
    _add_chunk(db, document)

    with pytest.raises(IntegrityError):
        _add_chunk(db, document)
    db.session.rollback()
