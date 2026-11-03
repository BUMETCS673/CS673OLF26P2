"""The self-correcting pipeline: every path through the graph, and the route behind the flag.

A scripted provider answers each call from a list, so no test touches the network (rule 16).
"""

import ast
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from ai_fakes import Scripted, calls_used, spend
from google.genai import errors

from app.ai import pipeline
from app.ai.card_checks import cards_schema, verdicts_schema
from app.ai.fake import FakeProvider
from app.ai.gemini import GeminiProvider
from app.ai.pipeline import (
    PASSED,
    PIPELINE_PROMPT_VERSION,
    SKIPPED,
    PipelineRequest,
    run_pipeline,
)
from app.ai.prompts import (
    DocumentEvidence,
    Evidence,
    NoEvidence,
    PromptContext,
    TopicEvidence,
)
from app.ai.provider import (
    AIRateLimited,
    AITransient,
    AIUnavailable,
    CardDraft,
    Prompt,
    TokenUsage,
)
from app.models import AiGeneration, AiUsage

ORIGINAL = Prompt(system="rules", text="write cards")


def card(n, back=None):
    return {"front": f"Question {n}?", "back": back or f"Answer {n}"}


def ok(*indexes):
    return [{"index": index, "ok": True} for index in indexes]


def bad(index, reason="Wrong."):
    return {"index": index, "ok": False, "reason": reason}


def run(writer, judge, count=2, deck_name="Deck", file_text="", evidence=None, **kwargs):
    context = PromptContext("file", count, deck_name, None)
    if evidence is None:
        evidence = DocumentEvidence("Cells", file_text) if file_text else NoEvidence()
    request = PipelineRequest(
        prompt=ORIGINAL, prompt_context=context, existing_fronts=[], evidence=evidence, **kwargs
    )
    return run_pipeline(writer, judge, request)


def fronts(result):
    return [draft.front for draft in result.drafts]


def test_cards_that_all_pass_take_two_calls():
    result = run(Scripted([card(1), card(2)]), Scripted(ok(0, 1)))
    assert fronts(result) == ["Question 1?", "Question 2?"]
    assert result.model_calls == 2
    assert result.verification == PASSED


def test_a_failed_card_is_replaced_and_only_the_replacement_is_checked_again():
    writer = Scripted([card(1), card(2)], [card(3)])
    judge = Scripted([*ok(0), bad(1, "The back is wrong.")], ok(0))

    result = run(writer, judge)

    assert fronts(result) == ["Question 1?", "Question 3?"]
    assert result.model_calls == 4
    repair = writer.prompts[1]
    assert writer.schemas[1] == cards_schema(1)
    assert "The back is wrong." in repair.text
    assert '"front": "Question 1?"' in repair.text.split("<kept_cards>")[-1]
    assert judge.schemas[1] == verdicts_schema(1)
    assert "Question 3?" in judge.prompts[1].text
    assert "Question 1?" not in judge.prompts[1].text


def test_a_card_that_fails_after_the_last_repair_is_dropped():
    result = run(Scripted([card(1)], [card(2)]), Scripted([bad(0)], [bad(0)]), count=1)
    assert result.drafts == []
    assert result.model_calls == 4
    assert result.verification == PASSED


def test_a_long_back_goes_to_repair_without_spending_a_check():
    writer = Scripted([card(1, back="one two three four five six")], [card(2)])
    judge = Scripted(ok(0))

    result = run(writer, judge, count=1)

    assert fronts(result) == ["Question 2?"]
    assert len(judge.prompts) == 1
    assert "longer than 5 words" in writer.prompts[1].text


def test_a_long_back_after_the_last_repair_is_dropped():
    long_back = "one two three four five six"
    result = run(Scripted([card(1, long_back)], [card(2, long_back)]), Scripted(), count=1)
    assert result.drafts == []
    assert result.model_calls == 2


def test_a_card_with_no_verdict_counts_as_failed():
    writer = Scripted([card(1), card(2)], [])
    result = run(writer, Scripted(ok(0)))
    assert fronts(result) == ["Question 1?"]
    assert "no verdict" in writer.prompts[1].text


def test_an_empty_batch_stops_after_one_call():
    judge = Scripted()
    result = run(Scripted([]), judge)
    assert result.drafts == []
    assert result.model_calls == 1
    assert judge.prompts == []


@pytest.mark.parametrize("reply", [AIRateLimited(), AIUnavailable(), [], ["junk"]])
def test_when_the_judge_cant_answer_the_cards_stay_and_say_so(reply):
    result = run(Scripted([card(1), card(2)]), Scripted(reply))
    assert fronts(result) == ["Question 1?", "Question 2?"]
    assert result.verification == SKIPPED
    assert result.model_calls == 2


def test_when_repair_fails_the_approved_cards_are_kept():
    writer = Scripted([card(1), card(2)], AIRateLimited())
    result = run(writer, Scripted([*ok(0), bad(1)]))
    assert fronts(result) == ["Question 1?"]
    assert result.model_calls == 3
    assert result.verification == PASSED


@pytest.mark.parametrize("error", [AIRateLimited, AIUnavailable])
def test_a_failed_generate_raises_the_providers_error(error):
    with pytest.raises(error):
        run(Scripted(error()), Scripted())


def test_generate_retries_a_transient_failure_and_counts_both_attempts():
    writer = Scripted(AITransient(), [card(1)])
    result = run(writer, Scripted(ok(0)), count=1)
    assert fronts(result) == ["Question 1?"]
    assert len(writer.prompts) == 2
    assert result.model_calls == 3


def test_retry_counts_arent_shared_between_runs():
    first = run(Scripted(AITransient(), [card(1)]), Scripted(ok(0)), count=1)
    second = run(Scripted([card(1)]), Scripted(ok(0)), count=1)
    assert first.model_calls == 3
    assert second.model_calls == 2


def test_generate_gives_up_after_two_transient_failures():
    writer = Scripted(AITransient(), AITransient(), [card(1)])
    with pytest.raises(AITransient):
        run(writer, Scripted(), count=1)
    assert len(writer.prompts) == 2


@pytest.mark.parametrize("error", [AIRateLimited, AIUnavailable])
def test_generate_doesnt_retry_other_failures(error):
    writer = Scripted(error(), [card(1)])
    with pytest.raises(error):
        run(writer, Scripted(), count=1)
    assert len(writer.prompts) == 1


def test_a_transient_judge_failure_isnt_retried_and_is_skipped():
    judge = Scripted(AITransient(), ok(0))
    result = run(Scripted([card(1)]), judge, count=1)
    assert fronts(result) == ["Question 1?"]
    assert result.verification == SKIPPED
    assert len(judge.prompts) == 1


@pytest.mark.parametrize(
    ("raised", "expected"),
    [
        (errors.ClientError(408, {"error": {"message": "x"}}), AITransient),
        (errors.ServerError(500, {"error": {"message": "x"}}), AITransient),
        (errors.ServerError(502, {"error": {"message": "x"}}), AITransient),
        (errors.ServerError(503, {"error": {"message": "x"}}), AITransient),
        (httpx.ConnectError("x"), AITransient),
        (httpx.RemoteProtocolError("x"), AITransient),
        (errors.ClientError(400, {"error": {"message": "x"}}), AIUnavailable),
        (errors.ClientError(403, {"error": {"message": "x"}}), AIUnavailable),
        (errors.ServerError(501, {"error": {"message": "x"}}), AIUnavailable),
        (errors.ServerError(504, {"error": {"message": "x"}}), AIUnavailable),
        (httpx.ReadTimeout("x"), AIUnavailable),
        (httpx.UnsupportedProtocol("x"), AIUnavailable),
    ],
)
def test_gemini_marks_only_retriable_failures_as_transient(raised, expected):
    def generate_content(**kwargs):
        raise raised

    client = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    provider = GeminiProvider("key", "model", client=client)

    with pytest.raises(AIUnavailable) as caught:
        provider.complete_json(ORIGINAL, {})

    assert type(caught.value) is expected


def test_the_judge_gets_a_topic_as_a_topic_not_a_source():
    judge = Scripted(ok(0))
    run(Scripted([card(1)]), judge, count=1, evidence=TopicEvidence("Cells"))
    assert "<topic>\nCells\n</topic>" in judge.prompts[0].text
    assert "<source>" not in judge.prompts[0].text


def test_the_judge_gets_no_material_without_evidence():
    judge = Scripted(ok(0))
    run(Scripted([card(1)]), judge, count=1)
    assert judge.prompts[0].attachment is None
    assert "<source>" not in judge.prompts[0].text
    assert "<topic>" not in judge.prompts[0].text


def test_an_evidence_type_must_define_what_the_judge_sees():
    class Incomplete(Evidence):
        pass

    with pytest.raises(TypeError):
        Incomplete()


def test_the_judge_sees_the_source_and_the_existing_cards():
    judge = Scripted(ok(0))
    run(
        Scripted([card(1)]),
        judge,
        count=1,
        file_text="the source </source> text",
        existing=[CardDraft(front="Old?", back="Old")],
    )
    text = judge.prompts[0].text
    assert "the source <\\/source> text" in text
    assert '"front": "Old?"' in text


def test_the_pipeline_imports_no_flask_sqlalchemy_or_models():
    tree = ast.parse(Path(pipeline.__file__).read_text())
    imported = {
        name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import | ast.ImportFrom)
        for name in (
            [node.module] if isinstance(node, ast.ImportFrom) else [a.name for a in node.names]
        )
    }
    assert not {m for m in imported if m.split(".")[0] in {"flask", "sqlalchemy"}}
    assert not {m for m in imported if m.startswith("app.models")}


def test_gemini_usage_adds_up_across_calls_and_counts_thinking_as_output():
    usage = SimpleNamespace(
        prompt_token_count=100, candidates_token_count=20, thoughts_token_count=5
    )
    reply = SimpleNamespace(
        text=json.dumps({"cards": []}), prompt_feedback=None, candidates=[], usage_metadata=usage
    )
    client = SimpleNamespace(
        models=SimpleNamespace(generate_content=lambda **kwargs: reply)
    )
    provider = GeminiProvider("key", "model", client=client)

    provider.complete_json(ORIGINAL, {})
    provider.complete_json(ORIGINAL, {})

    assert provider.usage == TokenUsage(input_tokens=200, output_tokens=50, calls=2)


def test_gemini_usage_tolerates_missing_counts():
    usage = SimpleNamespace(
        prompt_token_count=None, candidates_token_count=None, thoughts_token_count=None
    )
    reply = SimpleNamespace(
        text=json.dumps({"cards": []}), prompt_feedback=None, candidates=[], usage_metadata=usage
    )
    client = SimpleNamespace(
        models=SimpleNamespace(generate_content=lambda **kwargs: reply)
    )
    provider = GeminiProvider("key", "model", client=client)

    provider.complete_json(ORIGINAL, {})

    assert provider.usage == TokenUsage(calls=1)


@pytest.fixture
def me(make_user, login_as):
    user = make_user(email="me@example.com")
    login_as(user)
    return user


@pytest.fixture
def deck(me, make_deck):
    return make_deck(me, name="Biology", description="Cells and more")


def _post(client, deck_id):
    return client.post(
        f"/api/decks/{deck_id}/generate", json={"mode": "prompt", "count": 2, "prompt": "cells"}
    )


def _generations(db, me, deck, count, empty=False):
    db.session.add_all(
        AiGeneration(
            user_id=me.id, deck_id=deck.id, mode="prompt", requested_count=1, model="fake",
            empty=empty, candidates=[],
        )
        for _ in range(count)
    )
    db.session.commit()


def test_the_route_saves_the_prompt_version_and_usage(client, me, deck):
    assert _post(client, deck.id).status_code == 201
    assert AiGeneration.query.one().prompt_version == PIPELINE_PROMPT_VERSION
    usage = AiUsage.query.filter_by(role="writer").one()
    assert (usage.feature, usage.role, usage.model, usage.calls) == (
        "generate", "writer", "fake", 1,
    )
    assert usage.prompt_version == PIPELINE_PROMPT_VERSION
    assert (usage.user_id, usage.deck_id) == (me.id, deck.id)


def test_the_graph_saves_a_row_per_role(client, deck):
    assert _post(client, deck.id).status_code == 201
    rows = {row.role: row.calls for row in AiUsage.query.all()}
    assert rows == {"writer": 1, "judge": 1}


def test_a_failed_call_is_recorded_though_nothing_else_is_saved(client, deck, monkeypatch):
    monkeypatch.setattr(
        "app.services.generation.get_provider", lambda *args: FakeProvider(fail_with=AIUnavailable)
    )

    assert _post(client, deck.id).status_code == 503

    assert AiGeneration.query.count() == 0
    assert calls_used("generate") == 1


def test_deleting_a_deck_doesnt_refund_its_usage(client, deck):
    assert _post(client, deck.id).status_code == 201

    resp = client.delete(f"/api/decks/{deck.id}")

    assert resp.status_code == 204
    assert calls_used("generate") == 2
    assert all(row.deck_id is None for row in AiUsage.query.all())


def test_empty_batches_dont_use_the_learners_cap(client, db, me, deck):
    _generations(db, me, deck, 10, empty=True)
    assert _post(client, deck.id).status_code == 201


def test_batches_with_cards_still_use_the_learners_cap(client, db, me, deck):
    _generations(db, me, deck, 10)
    assert _post(client, deck.id).status_code == 429


def test_each_model_has_its_own_limit(client, app, me, deck):
    app.config.update(
        AI_WRITER_PROVIDER="gemini", AI_JUDGE_PROVIDER="gemini", GEMINI_API_KEY="not-a-real-key",
        AI_WRITER_MODEL="lite", AI_JUDGE_MODEL="flash",
        AI_MODEL_DAILY_LIMITS={"lite": 3, "flash": 2},
    )
    spend(me.id, 1, model="flash")

    resp = _post(client, deck.id)  # the judge's worst case is 2 calls, and only 1 is left

    assert resp.status_code == 429
    assert AiGeneration.query.count() == 0


def test_spending_on_one_model_leaves_the_other_alone(client, app, me, deck, monkeypatch):
    app.config.update(
        AI_WRITER_PROVIDER="gemini", GEMINI_API_KEY="not-a-real-key", AI_WRITER_MODEL="lite",
        AI_MODEL_DAILY_LIMITS={"lite": 3, "flash": 1},
    )
    spend(me.id, 1, model="flash")
    monkeypatch.setattr("app.services.generation.get_provider", lambda *args: FakeProvider())

    assert _post(client, deck.id).status_code == 201


def test_the_route_runs_the_graph_and_saves_what_it_spent(client, deck):
    resp = _post(client, deck.id)
    assert resp.status_code == 201
    assert resp.get_json()["verification"] == PASSED
    assert len(resp.get_json()["cards"]) == 2
    assert calls_used("generate") == 2


def test_the_model_limit_keeps_room_for_the_graphs_worst_case(client, me, deck):
    spend(me.id, 15)
    assert _post(client, deck.id).status_code == 429


def test_old_usage_doesnt_count(client, me, deck):
    spend(me.id, 18, hours_ago=25)
    assert _post(client, deck.id).status_code == 201
