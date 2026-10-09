"""Step 0a's own tests: what Iteration 3's AI tasks build on.

One test per acceptance example under Step 0a in code/plans/ITERATION_3_PLAN.md, plus the
pieces of the C6 contract that 0a writes in full. B1 to B4 test their own work in their
own files.

Nothing here tests the stubs 0a leaves for others to fill in: `build_prompt()`,
`clean_drafts()`, `GeminiProvider.generate_cards()` and `flask ai-smoke`. Those change
when B1 and B2 merge, and this file shouldn't break when they do.
"""

# AI Utilization: ~100% of this file's code
# AI Tools Used: Claude Code (Claude Opus 5.5)
# AI-Assisted Activities:
#   Unit test creation (from the plan's acceptance examples)
# Human role: plan approval, code review, and hands-on testing by Miles Cameron.

import pytest

from app.ai.provider import (
    NOT_CONFIGURED,
    QUOTA_USED_UP,
    UNAVAILABLE,
    AIRateLimited,
    AIUnavailable,
    FakeProvider,
    GeminiProvider,
    Prompt,
    cards_schema,
    get_provider,
)
from app.errors import ApiError
from app.models import AiGeneration, Card, as_utc, utcnow


def _prompt(max_cards=3):
    return Prompt(system="rules", text="Deck name: Anatomy", max_cards=max_cards)


def _generation(db, user, deck, candidates):
    generation = AiGeneration(
        user_id=user.id,
        deck_id=deck.id,
        mode="prompt",
        prompt="The bones of the hand",
        requested_count=10,
        model="fake",
        candidates=candidates,
    )
    db.session.add(generation)
    db.session.commit()
    return generation


# --- Card.origin (C1) -------------------------------------------------------------------


def test_a_card_made_through_the_api_is_manual_in_the_list_and_in_study(
    client, make_user, login_as, make_deck
):
    user = make_user()
    login_as(user)
    deck = make_deck(user)

    created = client.post(
        f"/api/decks/{deck.id}/cards", json={"front": "la biblioteca", "back": "the library"}
    )
    assert created.status_code == 201

    [listed] = client.get(f"/api/decks/{deck.id}/cards").get_json()
    [studied] = client.get(f"/api/decks/{deck.id}/due").get_json()["new"]

    assert listed["origin"] == "manual"
    assert studied["origin"] == "manual"


def test_origin_comes_right_after_due_at_and_generation_id_stays_internal(
    make_user, make_deck
):
    deck = make_deck(make_user(), cards=[("la biblioteca", "the library")])

    payload = deck.cards[0].to_dict()

    keys = list(payload)
    assert keys[keys.index("due_at") + 1] == "origin"
    assert "generation_id" not in payload


# --- AiGeneration (Database changes, C3) -------------------------------------------------


def test_a_generation_serializes_to_the_c3_shape(db, make_user, make_deck):
    user = make_user()
    deck = make_deck(user)
    generation = _generation(
        db,
        user,
        deck,
        [
            {"front": "Which wrist bone fractures most often?", "back": "Scaphoid",
             "status": "pending"},
            {"front": "How many bones are in the hand?", "back": "27", "status": "rejected"},
        ],
    )

    payload = generation.to_dict()

    assert list(payload) == [
        "id", "deck_id", "mode", "requested_count", "model", "created_at", "cards",
    ]
    assert payload["deck_id"] == deck.id
    assert payload["mode"] == "prompt"
    assert payload["requested_count"] == 10
    assert payload["model"] == "fake"
    assert payload["created_at"].endswith("Z")
    assert payload["cards"] == [
        {"index": 0, "front": "Which wrist bone fractures most often?", "back": "Scaphoid",
         "status": "pending"},
        {"index": 1, "front": "How many bones are in the hand?", "back": "27",
         "status": "rejected"},
    ]
    assert not {"user_id", "prompt", "source_filename"} & set(payload)


def test_deleting_a_deck_deletes_its_generations_and_their_cards(db, make_user, make_deck):
    user = make_user()
    deck = make_deck(user)
    generation = _generation(
        db, user, deck, [{"front": "q", "back": "a", "status": "accepted"}]
    )
    db.session.add(Card(deck=deck, front="q", back="a", origin="ai", generation_id=generation.id))
    db.session.commit()

    db.session.delete(deck)
    db.session.commit()

    assert AiGeneration.query.count() == 0
    assert Card.query.count() == 0


def test_deleting_a_generation_keeps_its_cards(db, make_user, make_deck):
    """generation_id is ON DELETE SET NULL: the card is the learner's now."""
    user = make_user()
    deck = make_deck(user)
    generation = _generation(
        db, user, deck, [{"front": "q", "back": "a", "status": "accepted"}]
    )
    card = Card(deck=deck, front="q", back="a", origin="ai", generation_id=generation.id)
    db.session.add(card)
    db.session.commit()

    db.session.delete(generation)
    db.session.commit()
    db.session.expire_all()

    assert card.generation_id is None
    assert card.origin == "ai"


def test_created_at_is_set_on_insert(db, make_user, make_deck):
    """The daily cap counts generations by created_at (C2)."""
    user = make_user()
    deck = make_deck(user)
    before = utcnow()

    generation = _generation(db, user, deck, [])

    assert as_utc(generation.created_at) >= before


# --- The provider (C6) -------------------------------------------------------------------


def test_the_stand_in_numbers_its_samples_across_calls():
    provider = FakeProvider()

    first = provider.generate_cards(_prompt(max_cards=3))
    second = provider.generate_cards(_prompt(max_cards=3))

    assert len(first) == 3
    assert len(second) == 3
    assert len({card["front"] for card in first + second}) == 6
    for card in first + second:
        assert card["front"].startswith("Sample question ")
        assert card["back"].startswith("Sample answer ")
        assert card["front"].removeprefix("Sample question ") == card["back"].removeprefix(
            "Sample answer "
        )


def test_the_stand_in_can_fail_like_google():
    with pytest.raises(AIRateLimited) as raised:
        FakeProvider(fail_with=AIRateLimited).generate_cards(_prompt())

    assert raised.value.message == (
        "The free AI service is at its limit right now. Wait a minute and try again. "
        "If it still doesn't work, today's free limit is used up and resets overnight."
    )
    assert raised.value.message == QUOTA_USED_UP


def test_ai_unavailable_defaults_to_the_outage_message():
    assert AIUnavailable().message == UNAVAILABLE == (
        "The AI service didn't respond. Try again in a minute."
    )
    assert AIUnavailable(NOT_CONFIGURED).message == NOT_CONFIGURED


def test_the_schema_caps_the_list_at_the_requested_count():
    schema = cards_schema(7)

    assert schema["required"] == ["cards"]
    assert schema["properties"]["cards"]["maxItems"] == 7
    assert schema["properties"]["cards"]["items"]["required"] == ["front", "back"]


def test_tests_use_the_stand_in_and_no_key(app):
    """Rule 16: no test reaches Google, and a key in someone's .env never reaches a test."""
    assert app.config["AI_PROVIDER"] == "fake"
    assert app.config["GEMINI_API_KEY"] == ""


def test_the_fake_setting_gives_the_stand_in(app):
    app.config["AI_PROVIDER"] = "fake"

    assert isinstance(get_provider(), FakeProvider)
    assert get_provider().name == "fake"


def test_gemini_without_a_key_is_not_set_up(app):
    app.config["AI_PROVIDER"] = "gemini"
    app.config["GEMINI_API_KEY"] = ""

    with pytest.raises(AIUnavailable) as raised:
        get_provider()

    assert raised.value.message == "AI generation isn't set up on this server."


def test_gemini_with_a_key_is_named_after_the_model(app):
    """Building the client makes no request, so this stays off the network."""
    app.config["AI_PROVIDER"] = "gemini"
    app.config["GEMINI_API_KEY"] = "not-a-real-key"
    app.config["GEMINI_MODEL"] = "gemini-test-model"

    provider = get_provider()

    assert isinstance(provider, GeminiProvider)
    assert provider.name == "gemini-test-model"


def test_an_unknown_provider_setting_is_not_set_up(app):
    app.config["AI_PROVIDER"] = "openai"

    with pytest.raises(AIUnavailable) as raised:
        get_provider()

    assert raised.value.message == NOT_CONFIGURED


# --- Settings ----------------------------------------------------------------------------


def test_tests_run_with_the_plans_limits(app):
    """Pinned in TestConfig, so AI_DAILY_LIMIT=2 left in .env (walkthrough step 14)
    can't change what B3's cap tests count to."""
    assert app.config["AI_MAX_CARDS"] == 25
    assert app.config["AI_DAILY_LIMIT"] == 10


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, "fallback"),     # unset
        ("", "fallback"),       # compose passes an unset ${VAR:-} through as ""
        ("   ", "fallback"),
        ("gemini", "gemini"),
    ],
)
def test_a_blank_setting_falls_back_to_its_default(monkeypatch, value, expected):
    from app.config import _env

    if value is None:
        monkeypatch.delenv("CADENCE_TEST_SETTING", raising=False)
    else:
        monkeypatch.setenv("CADENCE_TEST_SETTING", value)

    assert _env("CADENCE_TEST_SETTING", "fallback") == expected


# --- Errors (C5) and wiring --------------------------------------------------------------


@pytest.mark.parametrize(("status", "code"), [(429, "rate_limited"), (503, "ai_unavailable")])
def test_the_new_statuses_have_contract_codes(app, status, code):
    with app.test_request_context():
        response, returned_status = ApiError(status, "message").to_response()

    assert returned_status == status
    assert response.get_json() == {"error": {"code": code, "message": "message"}}


def test_b3_can_import_everything_it_calls():
    """The stubs exist so B3 can import them before B1 merges (C6)."""
    from app.ai.cleanup import clean_drafts, normalize_front
    from app.ai.prompts import build_prompt

    assert all(callable(f) for f in (build_prompt, clean_drafts, normalize_front))


def test_both_ai_blueprints_are_registered(app):
    assert "api.generate" in app.blueprints
    assert "api.generations" in app.blueprints


def test_the_ai_smoke_command_is_registered(app):
    assert "ai-smoke" in app.cli.commands
