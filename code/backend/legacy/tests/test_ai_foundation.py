"""Step 0a's own tests: what Iteration 3's AI tasks build on.

One test per acceptance example under Step 0a, plus the
pieces of the C6 contract that 0a writes in full. B1 to B4 test their own work in their
own files.

Nothing here tests the stubs 0a leaves for others to fill in: `build_prompt()`,
`clean_drafts()`, `GeminiProvider.generate_cards()` and `flask ai-smoke`. Those change
when B1 and B2 merge, and this file shouldn't break when they do.
"""

# AI Utilization: ~100% of this file's code
# AI Tools Used: Claude Code (Claude Opus 5.5)
# AI-Assisted Activities:
#   Unit test creation
# Human role: plan approval, code review, and hands-on testing by Miles Cameron.

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool

from app.ai.card_checks import cards_schema, write_cards
from app.ai.fake import FakeProvider
from app.ai.gemini import GeminiProvider
from app.ai.provider import (
    DECLINED,
    EMBEDDING_DIMENSIONS,
    NOT_CONFIGURED,
    QUOTA_USED_UP,
    TOO_MUCH,
    UNAVAILABLE,
    AIRateLimited,
    AIUnavailable,
    Prompt,
    Provider,
    Role,
    get_provider,
    is_configured,
)
from app.errors import ApiError
from app.models import AiGeneration, Card, as_utc, utcnow


def _prompt():
    return Prompt(system="rules", text="Deck name: Anatomy")


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
        "id", "deck_id", "mode", "requested_count", "model", "verification", "created_at", "cards",
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

    first = write_cards(provider, _prompt(), 3)
    second = write_cards(provider, _prompt(), 3)

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
        FakeProvider(fail_with=AIRateLimited).complete_json(_prompt(), cards_schema(3))

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


def test_the_messages_that_dont_say_try_again():
    """C5's two Gemini messages for failures a retry won't fix (A20)."""
    assert TOO_MUCH == (
        "That was too much to turn into cards at once. Ask for fewer cards or use a shorter file."
    )
    assert DECLINED == "The AI declined to write cards from that material."
    assert AIUnavailable(DECLINED).message == DECLINED


def test_the_schema_caps_the_list_at_the_requested_count():
    schema = cards_schema(7)

    assert schema["required"] == ["cards"]
    assert schema["properties"]["cards"]["maxItems"] == 7
    assert schema["properties"]["cards"]["items"]["required"] == ["front", "back"]


def test_tests_use_the_stand_in_and_no_key(app):
    """Rule 16: no test reaches Google, and a key in someone's .env never reaches a test."""
    assert app.config["AI_WRITER_PROVIDER"] == "fake"
    assert app.config["GEMINI_API_KEY"] == ""


def test_the_fake_setting_gives_the_stand_in(app):
    app.config["AI_WRITER_PROVIDER"] = "fake"

    assert isinstance(get_provider(), FakeProvider)
    assert get_provider().name == "fake"


def test_gemini_without_a_key_is_not_set_up(app):
    app.config["AI_WRITER_PROVIDER"] = "gemini"
    app.config["GEMINI_API_KEY"] = ""

    with pytest.raises(AIUnavailable) as raised:
        get_provider()

    assert raised.value.message == "AI generation isn't set up on this server."


def test_gemini_with_a_key_is_named_after_the_model(app):
    """Building the client makes no request, so this stays off the network."""
    app.config["AI_WRITER_PROVIDER"] = "gemini"
    app.config["GEMINI_API_KEY"] = "not-a-real-key"
    app.config["AI_WRITER_MODEL"] = "gemini-test-model"

    provider = get_provider()

    assert isinstance(provider, GeminiProvider)
    assert provider.name == "gemini-test-model"


def test_each_role_has_its_own_vendor_and_model(app):
    app.config["AI_WRITER_PROVIDER"] = "fake"
    app.config["AI_JUDGE_PROVIDER"] = "gemini"
    app.config["AI_JUDGE_MODEL"] = "gemini-judge-model"
    app.config["GEMINI_API_KEY"] = "not-a-real-key"

    assert isinstance(get_provider("writer"), FakeProvider)
    assert isinstance(get_provider("judge"), GeminiProvider)
    assert get_provider("judge").name == "gemini-judge-model"


def test_each_role_has_its_own_thinking_level(app):
    app.config["AI_WRITER_PROVIDER"] = "gemini"
    app.config["GEMINI_API_KEY"] = "not-a-real-key"
    app.config["AI_WRITER_THINKING"] = "high"

    assert get_provider(Role.WRITER)._thinking.name == "HIGH"


def test_an_unknown_thinking_level_is_not_set_up(app):
    app.config["AI_WRITER_PROVIDER"] = "gemini"
    app.config["GEMINI_API_KEY"] = "not-a-real-key"
    app.config["AI_WRITER_THINKING"] = "extreme"

    with pytest.raises(AIUnavailable) as raised:
        get_provider()

    assert raised.value.message == NOT_CONFIGURED


def test_is_configured_checks_the_vendor_and_its_key(app):
    assert is_configured(Role.JUDGE) is True

    app.config["AI_JUDGE_PROVIDER"] = "openai"
    assert is_configured(Role.JUDGE) is False

    app.config["AI_JUDGE_PROVIDER"] = "gemini"
    app.config["GEMINI_API_KEY"] = ""
    assert is_configured(Role.JUDGE) is False

    app.config["GEMINI_API_KEY"] = "not-a-real-key"
    assert is_configured(Role.JUDGE) is True


def test_the_stand_in_answers_a_schema_it_has_never_seen():
    schema = {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": ["first", "second"]},
            "note": {"type": "string"},
            "rows": {
                "type": "array",
                "maxItems": 2,
                "items": {
                    "type": "object",
                    "properties": {"index": {"type": "integer"}, "ok": {"type": "boolean"}},
                },
            },
        },
    }

    reply = FakeProvider().complete_json(_prompt(), schema)

    assert reply["kind"] == "first"
    assert reply["note"].startswith("Sample note ")
    assert reply["rows"] == [{"index": 0, "ok": True}, {"index": 1, "ok": True}]


@pytest.mark.parametrize("text", [None, "not json", "[1, 2]", '"text"'])
def test_a_reply_that_isnt_a_json_object_is_unavailable(text):
    class Replying(Provider):
        def _complete(self, prompt, schema):
            return text

        def _embed(self, texts, is_query):
            return []

        def _chat(self, messages, tools, tool_choice):
            return AIMessage(content="")

    with pytest.raises(AIUnavailable):
        Replying("name").complete_json(_prompt(), {})


@tool
def _look_up(query: str) -> str:
    """Look something up."""
    return query


@tool
def _finish(answer: str) -> str:
    """Finish."""
    return answer


def test_the_stand_in_calls_the_last_tool_with_arguments_from_its_schema():
    provider = FakeProvider()

    [call] = provider.chat([HumanMessage("Hello")], [_look_up, _finish]).tool_calls

    assert call["name"] == "_finish"
    assert call["args"]["answer"]
    assert provider.usage.calls == 1


def test_the_stand_in_obeys_a_required_tool():
    messages = [HumanMessage("Hello")]

    reply = FakeProvider().chat(messages, [_look_up, _finish], tool_choice="_look_up")

    assert reply.tool_calls[0]["name"] == "_look_up"


def test_the_stand_in_can_fail_a_chat():
    with pytest.raises(AIRateLimited):
        FakeProvider(fail_with=AIRateLimited).chat([HumanMessage("Hello")], [_finish])


def test_chat_adds_up_the_tokens_it_used():
    class Counting(FakeProvider):
        def _chat(self, messages, tools, tool_choice):
            usage = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
            return AIMessage(content="", usage_metadata=usage)

    provider = Counting()

    provider.chat([HumanMessage("Hello")], [_finish])
    provider.chat([HumanMessage("Hello")], [_finish])

    assert (provider.usage.calls, provider.usage.input_tokens) == (2, 20)
    assert provider.usage.output_tokens == 10


def test_the_stand_in_gives_the_same_text_the_same_vector():
    first, other, again = FakeProvider().embed(["ATP", "DNA", "ATP"])

    assert len(first) == EMBEDDING_DIMENSIONS
    assert first == again
    assert first != other


def test_the_wrong_number_of_vectors_is_unavailable():
    class Short(FakeProvider):
        def _embed(self, texts, is_query):
            return []

    with pytest.raises(AIUnavailable):
        Short().embed(["ATP"])


def test_a_vector_of_the_wrong_size_is_unavailable():
    class Small(FakeProvider):
        def _embed(self, texts, is_query):
            return [[0.5]]

    with pytest.raises(AIUnavailable):
        Small().embed(["ATP"])


def test_a_provider_must_implement_complete():
    class Incomplete(Provider):
        pass

    with pytest.raises(TypeError):
        Incomplete("name")


def test_an_unknown_provider_setting_is_not_set_up(app):
    app.config["AI_WRITER_PROVIDER"] = "openai"

    with pytest.raises(AIUnavailable) as raised:
        get_provider()

    assert raised.value.message == NOT_CONFIGURED


# --- Settings ----------------------------------------------------------------------------


def test_tests_run_with_the_plans_limits(app):
    """Pinned in TestConfig, so AI_DAILY_LIMIT=2 left in .env (walkthrough step 14)
    can't change what B3's cap tests count to."""
    assert app.config["AI_MAX_CARDS"] == 25
    assert app.config["AI_DAILY_LIMIT"] == 10
    assert app.config["AI_MODEL_DAILY_LIMIT"] == 18
    assert app.config["AI_MODEL_DAILY_LIMITS"] == {}


def test_the_model_limits_default_to_18_and_read_the_environment(monkeypatch):
    import importlib

    import app.config

    monkeypatch.delenv("AI_MODEL_DAILY_LIMIT", raising=False)
    monkeypatch.delenv("AI_MODEL_DAILY_LIMITS", raising=False)
    config = importlib.reload(app.config).Config
    assert config.AI_MODEL_DAILY_LIMIT == 18
    assert config.AI_MODEL_DAILY_LIMITS == {
        "gemini-3.5-flash-lite": 450, "gemini-3.8-flash": 18, "gemini-embedding-001": 900,
    }

    monkeypatch.setenv("AI_MODEL_DAILY_LIMIT", "450")
    monkeypatch.setenv("AI_MODEL_DAILY_LIMITS", " lite:500 , flash:20 ")
    config = importlib.reload(app.config).Config
    assert config.AI_MODEL_DAILY_LIMIT == 450
    assert config.AI_MODEL_DAILY_LIMITS == {"lite": 500, "flash": 20}

    monkeypatch.delenv("AI_MODEL_DAILY_LIMIT")
    monkeypatch.delenv("AI_MODEL_DAILY_LIMITS")
    importlib.reload(app.config)


def test_a_malformed_model_limit_stops_the_app_starting(monkeypatch):
    import importlib

    import app.config

    monkeypatch.setenv("AI_MODEL_DAILY_LIMITS", "lite=500")
    with pytest.raises(ValueError):
        importlib.reload(app.config)

    monkeypatch.delenv("AI_MODEL_DAILY_LIMITS")
    importlib.reload(app.config)


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
    import app.config

    if value is None:
        monkeypatch.delenv("CADENCE_TEST_SETTING", raising=False)
    else:
        monkeypatch.setenv("CADENCE_TEST_SETTING", value)

    assert app.config._env("CADENCE_TEST_SETTING", "fallback") == expected


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


def test_startup_warns_about_a_renamed_setting(monkeypatch, caplog):
    import app.config

    monkeypatch.setenv("GEMINI_MODEL", "gemini-old")
    monkeypatch.setenv("AI_SITE_DAILY_LIMIT", "18")
    monkeypatch.setenv("AI_PROVIDER", "  ")  # compose passes an unset name through as blank

    app.create_app(app.config.TestConfig)

    assert "GEMINI_MODEL is no longer read and is being ignored. Use AI_WRITER_MODEL." in caplog.text
    assert "AI_SITE_DAILY_LIMIT is no longer read" in caplog.text
    assert "AI_PROVIDER" not in caplog.text
