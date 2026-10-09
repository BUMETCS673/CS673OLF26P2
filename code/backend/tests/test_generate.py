"""B3's tests for POST /api/decks/<id>/generate: one per acceptance example under B3 in
code/plans/ITERATION_3_PLAN.md, plus the log line and a few edges of C2.

`TestConfig` uses the stand-in. The failure rows, and the ones that look at the `Prompt`,
patch `app.api.generate.get_provider`.
"""

# AI Utilization: ~100% of this file's code
# AI Tools Used: Claude Code (Claude Opus 5.5)
# AI-Assisted Activities:
#   Unit test creation (from the plan's acceptance examples)
# Human role: plan review, code review, and CI verification by Duc Anh Nguyen.

import base64
import logging
from datetime import timedelta

import pytest

from app.ai.provider import (
    NOT_CONFIGURED,
    QUOTA_USED_UP,
    UNAVAILABLE,
    AIRateLimited,
    AIUnavailable,
    FakeProvider,
)
from app.models import AiGeneration, utcnow

PDF_BYTES = b"%PDF-1.7\n1 0 obj << >> endobj\n%%EOF\n"


class RecordingProvider:
    """Answers with `cards`, or the stand-in's samples, and keeps every `Prompt` it gets."""

    name = "recording"

    def __init__(self, cards=None, fail_with=None):
        self.cards = cards
        self.fail_with = fail_with
        self.prompts = []

    def generate_cards(self, prompt):
        self.prompts.append(prompt)
        if self.fail_with:
            raise self.fail_with
        if self.cards is not None:
            return self.cards
        return FakeProvider().generate_cards(prompt)


@pytest.fixture
def me(make_user, login_as):
    user = make_user(email="me@example.com")
    login_as(user)
    return user


@pytest.fixture
def deck(me, make_deck):
    return make_deck(me, name="Biology", description="Cells and more")


@pytest.fixture
def provider(monkeypatch):
    def _install(**kwargs):
        recording = RecordingProvider(**kwargs)
        monkeypatch.setattr("app.api.generate.get_provider", lambda: recording)
        return recording

    return _install


@pytest.fixture
def past_generation(db):
    def _past_generation(user, deck, hours_ago):
        db.session.add(
            AiGeneration(
                user_id=user.id,
                deck_id=deck.id,
                mode="prompt",
                requested_count=1,
                model="fake",
                candidates=[],
                created_at=utcnow() - timedelta(hours=hours_ago),
            )
        )
        db.session.commit()

    return _past_generation


def _post(client, deck_id, body, **kwargs):
    return client.post(f"/api/decks/{deck_id}/generate", json=body, **kwargs)


def _file_body(data: bytes, mime_type="application/pdf", name="notes.pdf", **extra):
    encoded = base64.b64encode(data).decode()
    return {"mode": "file", "count": 3, "file": {"name": name, "mime_type": mime_type, "data": encoded}, **extra}


def _error(resp):
    return resp.get_json()["error"]


def _generation_count():
    return AiGeneration.query.count()


# --- Success ------------------------------------------------------------------


def test_prompt_mode_returns_pending_cards_and_saves_one_row(client, deck):
    resp = _post(client, deck.id, {"mode": "prompt", "count": 3, "prompt": "Cells"})

    assert resp.status_code == 201
    body = resp.get_json()
    assert body["mode"] == "prompt"
    assert body["model"] == "fake"
    assert body["deck_id"] == deck.id
    assert body["requested_count"] == 3
    assert [c["index"] for c in body["cards"]] == [0, 1, 2]
    assert {c["status"] for c in body["cards"]} == {"pending"}
    row = AiGeneration.query.one()
    assert row.prompt == "Cells"
    assert row.source_filename is None


def test_the_provider_gets_the_trimmed_prompt_and_the_deck(client, deck, provider):
    recording = provider()

    _post(client, deck.id, {"mode": "prompt", "count": 4, "prompt": "  Mitosis  "})

    sent = recording.prompts[0]
    assert sent.max_cards == 4
    assert sent.text.startswith("Deck name: Biology\nDeck description: Cells and more")
    assert "<source>\nMitosis\n</source>" in sent.text


def test_a_card_matching_an_existing_front_is_left_out(client, me, make_deck, provider):
    deck = make_deck(me, cards=[("What is ATP?", "Energy carrier")])
    provider(cards=[{"front": "what is atp", "back": "x"}, {"front": "What is DNA?", "back": "y"}])

    resp = _post(client, deck.id, {"mode": "prompt", "count": 2, "prompt": "Cells"})

    assert [c["front"] for c in resp.get_json()["cards"]] == ["What is DNA?"]


def test_no_usable_cards_is_still_a_201_and_counts(client, deck, provider):
    provider(cards=[])

    resp = _post(client, deck.id, {"mode": "prompt", "count": 3, "prompt": "Cells"})

    assert resp.status_code == 201
    assert resp.get_json()["cards"] == []
    assert _generation_count() == 1


# --- Ownership, auth and the body ----------------------------------------------


def test_someone_elses_deck_is_404(client, me, make_user, make_deck):
    theirs = make_deck(make_user(email="them@example.com"))

    resp = _post(client, theirs.id, {"mode": "prompt", "count": 3, "prompt": "Cells"})

    assert resp.status_code == 404
    assert _error(resp)["message"] == "Deck not found"


def test_ownership_is_checked_before_the_body(client, me, make_user, make_deck):
    theirs = make_deck(make_user(email="them@example.com"))

    assert _post(client, theirs.id, {"mode": "quiz"}).status_code == 404


def test_signed_out_is_401(client, make_user, make_deck):
    deck = make_deck(make_user())

    assert _post(client, deck.id, {"mode": "prompt", "count": 3, "prompt": "x"}).status_code == 401


def test_a_body_that_isnt_an_object_is_400(client, deck):
    assert _post(client, deck.id, ["prompt"]).status_code == 400


def test_a_7_mb_body_is_400(client, deck):
    resp = client.post(
        f"/api/decks/{deck.id}/generate",
        data=b"x" * (7 * 1024 * 1024),
        content_type="application/json",
    )

    assert resp.status_code == 400
    assert _error(resp)["message"] == "Request body is too large."


# --- Fields ----------------------------------------------------------------------


@pytest.mark.parametrize("count", [0, 26, "5", True, 5.0, None])
def test_a_bad_count_is_422(client, deck, count):
    resp = _post(client, deck.id, {"mode": "prompt", "count": count, "prompt": "Cells"})

    assert resp.status_code == 422
    assert _error(resp) == {
        "code": "validation_error",
        "message": "count must be a whole number from 1 to 25.",
        "field": "count",
    }


@pytest.mark.parametrize("count", [1, 25])
def test_count_bounds_are_allowed(client, deck, count):
    resp = _post(client, deck.id, {"mode": "prompt", "count": count, "prompt": "Cells"})

    assert resp.status_code == 201


@pytest.mark.parametrize("mode", ["quiz", None, "PROMPT"])
def test_a_bad_mode_is_422(client, deck, mode):
    resp = _post(client, deck.id, {"mode": mode, "count": 3})

    assert resp.status_code == 422
    assert _error(resp)["field"] == "mode"


@pytest.mark.parametrize(
    ("prompt", "message"),
    [
        ("   ", "prompt is required."),
        (None, "prompt is required."),
        (7, "prompt is required."),
        ("x" * 2001, "prompt must be at most 2000 characters."),
    ],
)
def test_a_bad_prompt_is_422(client, deck, prompt, message):
    resp = _post(client, deck.id, {"mode": "prompt", "count": 3, "prompt": prompt})

    assert resp.status_code == 422
    assert _error(resp)["field"] == "prompt"
    assert _error(resp)["message"] == message


def test_count_is_checked_before_prompt(client, deck):
    resp = _post(client, deck.id, {"mode": "prompt", "count": 0, "prompt": ""})

    assert _error(resp)["field"] == "count"


# --- File mode ---------------------------------------------------------------------


def test_a_pdf_goes_to_the_provider_as_an_attachment(client, deck, provider):
    recording = provider()

    resp = _post(client, deck.id, _file_body(PDF_BYTES, focus=" Chapter 2 "))

    assert resp.status_code == 201
    sent = recording.prompts[0]
    assert sent.attachment.mime_type == "application/pdf"
    assert sent.attachment.data == PDF_BYTES
    assert "<source>" not in sent.text
    assert "<focus>\nChapter 2\n</focus>" in sent.text
    row = AiGeneration.query.one()
    assert row.source_filename == "notes.pdf"
    assert row.prompt == "Chapter 2"
    assert row.mode == "file"


def test_a_markdown_file_goes_into_the_prompt_text(client, deck, provider):
    recording = provider()
    notes = "﻿# Cells\nThe nucleus holds DNA.".encode()

    resp = _post(client, deck.id, _file_body(notes, mime_type="text/markdown", name="cells.md"))

    assert resp.status_code == 201
    sent = recording.prompts[0]
    assert sent.attachment is None
    assert "<source>\n# Cells\nThe nucleus holds DNA.\n</source>" in sent.text
    assert AiGeneration.query.one().prompt is None


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({"mode": "file", "count": 3}, "file is required."),
        ({"mode": "file", "count": 3, "file": "notes.pdf"}, "file is required."),
        ({"mode": "file", "count": 3, "file": {"name": "a.pdf", "mime_type": "application/pdf"}}, "file is required."),
        (_file_body(PDF_BYTES, name="n" * 256), "The file name must be at most 255 characters."),
        (
            _file_body(PDF_BYTES, mime_type="application/msword", name="notes.doc"),
            "Only PDF, TXT and MD files are supported. Save other documents as a PDF first.",
        ),
        (
            {"mode": "file", "count": 3, "file": {"name": "a.pdf", "mime_type": "application/pdf", "data": "%%%"}},
            "That file couldn't be read.",
        ),
        (_file_body(b""), "That file couldn't be read."),
        (_file_body(b"just text"), "That file isn't a valid PDF."),
        (_file_body(b"\xff\xfe\xfa", mime_type="text/plain", name="a.txt"), "That text file isn't UTF-8 text."),
        (
            _file_body(b"x" * 100_001, mime_type="text/plain", name="a.txt"),
            "That text file is too long. Split it into files under 100,000 characters.",
        ),
    ],
)
def test_a_bad_file_is_422(client, deck, body, message):
    resp = _post(client, deck.id, body)

    assert resp.status_code == 422
    assert _error(resp)["field"] == "file"
    assert _error(resp)["message"] == message


def test_a_text_file_of_exactly_100000_characters_is_allowed(client, deck):
    body = _file_body(b"x" * 100_000, mime_type="text/plain", name="a.txt")

    assert _post(client, deck.id, body).status_code == 201


def test_a_pdf_over_4_mb_is_422_not_400(client, deck):
    big = PDF_BYTES + b"0" * (4 * 1024 * 1024 + 1 - len(PDF_BYTES))

    resp = _post(client, deck.id, _file_body(big))

    assert resp.status_code == 422
    assert _error(resp)["field"] == "file"
    assert _error(resp)["message"] == "The file must be 4 MB or smaller."


def test_a_focus_over_500_characters_is_422(client, deck):
    resp = _post(client, deck.id, _file_body(PDF_BYTES, focus="f" * 501))

    assert resp.status_code == 422
    assert _error(resp) == {
        "code": "validation_error",
        "message": "focus must be at most 500 characters.",
        "field": "focus",
    }


# --- Suggest mode -----------------------------------------------------------------


def test_suggest_needs_ten_cards_in_the_deck(client, me, make_deck, make_card):
    deck = make_deck(me, cards=[(f"Q{i}?", f"A{i}") for i in range(9)])

    resp = _post(client, deck.id, {"mode": "suggest", "count": 3})

    assert resp.status_code == 422
    assert _error(resp) == {
        "code": "validation_error",
        "message": "Suggest more content needs at least 10 cards in the deck.",
        "field": "mode",
    }

    make_card(deck, front="Q9?", back="A9")
    assert _post(client, deck.id, {"mode": "suggest", "count": 3}).status_code == 201


def test_suggest_sends_the_newest_cards_and_ignores_a_prompt(client, me, make_deck, provider):
    deck = make_deck(me, cards=[(f"Question {i}?", f"Answer {i}") for i in range(10)])
    recording = provider()

    resp = _post(client, deck.id, {"mode": "suggest", "count": 3, "prompt": "Ignore me"})

    assert resp.status_code == 201
    sent = recording.prompts[0].text
    assert "Ignore me" not in sent
    assert sent.index("Question 9?") < sent.index("Question 0?")
    assert AiGeneration.query.one().prompt is None


# --- Daily caps -------------------------------------------------------------------


def test_the_eleventh_generation_in_24_hours_is_429(client, me, deck, past_generation):
    for _ in range(10):
        past_generation(me, deck, hours_ago=1)

    resp = _post(client, deck.id, {"mode": "prompt", "count": 3, "prompt": "Cells"})

    assert resp.status_code == 429
    assert _error(resp) == {
        "code": "rate_limited",
        "message": "You've reached the limit of 10 AI generations in 24 hours. Try again later.",
    }
    assert _generation_count() == 10


def test_a_generation_older_than_24_hours_doesnt_count(client, me, deck, past_generation):
    for _ in range(9):
        past_generation(me, deck, hours_ago=1)
    past_generation(me, deck, hours_ago=25)

    assert _post(client, deck.id, {"mode": "prompt", "count": 3, "prompt": "Cells"}).status_code == 201


def test_the_per_user_message_uses_the_configured_limit(app, client, me, deck, past_generation):
    app.config["AI_DAILY_LIMIT"] = 2
    past_generation(me, deck, hours_ago=1)
    past_generation(me, deck, hours_ago=1)

    resp = _post(client, deck.id, {"mode": "prompt", "count": 3, "prompt": "Cells"})

    assert _error(resp)["message"] == (
        "You've reached the limit of 2 AI generations in 24 hours. Try again later."
    )


def test_the_site_cap_counts_everyone(client, deck, make_user, make_deck, past_generation):
    others = make_user(email="others@example.com")
    their_deck = make_deck(others)
    for _ in range(18):
        past_generation(others, their_deck, hours_ago=1)

    resp = _post(client, deck.id, {"mode": "prompt", "count": 3, "prompt": "Cells"})

    assert resp.status_code == 429
    assert _error(resp) == {
        "code": "rate_limited",
        "message": "AI generation has hit today's limit for the whole site. Try again later.",
    }
    assert _generation_count() == 18


def test_the_site_cap_ignores_old_generations(client, deck, make_user, make_deck, past_generation):
    others = make_user(email="others@example.com")
    their_deck = make_deck(others)
    for _ in range(17):
        past_generation(others, their_deck, hours_ago=1)
    past_generation(others, their_deck, hours_ago=25)

    assert _post(client, deck.id, {"mode": "prompt", "count": 3, "prompt": "Cells"}).status_code == 201


def test_the_caps_come_after_the_fields(client, me, deck, past_generation):
    for _ in range(10):
        past_generation(me, deck, hours_ago=1)

    assert _post(client, deck.id, {"mode": "prompt", "count": 0}).status_code == 422


# --- The provider failing ------------------------------------------------------------


def test_googles_limit_is_429_and_saves_nothing(client, deck, provider):
    provider(fail_with=AIRateLimited())

    resp = _post(client, deck.id, {"mode": "prompt", "count": 3, "prompt": "Cells"})

    assert resp.status_code == 429
    assert _error(resp) == {"code": "rate_limited", "message": QUOTA_USED_UP}
    assert _generation_count() == 0


def test_an_unavailable_provider_is_503_and_saves_nothing(client, deck, provider):
    provider(fail_with=AIUnavailable())

    resp = _post(client, deck.id, {"mode": "prompt", "count": 3, "prompt": "Cells"})

    assert resp.status_code == 503
    assert _error(resp) == {"code": "ai_unavailable", "message": UNAVAILABLE}
    assert _generation_count() == 0


def test_a_reply_that_isnt_a_list_is_503(client, deck, provider):
    provider(cards={"cards": []})

    resp = _post(client, deck.id, {"mode": "prompt", "count": 3, "prompt": "Cells"})

    assert resp.status_code == 503
    assert _generation_count() == 0


def test_gemini_with_no_key_is_503_not_set_up(app, client, deck):
    app.config["AI_PROVIDER"] = "gemini"
    app.config["GEMINI_API_KEY"] = ""

    resp = _post(client, deck.id, {"mode": "prompt", "count": 3, "prompt": "Cells"})

    assert resp.status_code == 503
    assert _error(resp)["message"] == NOT_CONFIGURED


# --- Logging (rule 17) ----------------------------------------------------------------


def test_one_log_line_with_no_user_content(client, deck, caplog):
    caplog.set_level(logging.INFO)

    _post(client, deck.id, {"mode": "prompt", "count": 3, "prompt": "Secret topic"})

    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("ai_generation")]
    assert len(lines) == 1
    assert lines[0].startswith("ai_generation mode=prompt count=3 kept=3 model=fake ms=")
    assert lines[0].endswith("outcome=ok")
    assert "Secret topic" not in caplog.text
    assert "Sample" not in caplog.text


def test_the_app_logs_at_info_outside_debug(app):
    assert not app.debug
    assert app.logger.isEnabledFor(logging.INFO)


def test_a_failure_is_logged_with_its_outcome(client, deck, provider, caplog):
    caplog.set_level(logging.INFO)
    provider(fail_with=AIUnavailable())

    _post(client, deck.id, {"mode": "prompt", "count": 3, "prompt": "Cells"})

    assert "model=recording" in caplog.text
    assert "outcome=unavailable" in caplog.text
