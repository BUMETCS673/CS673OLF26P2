"""The self-correcting pipeline: every path through the graph, and the route behind the flag.

A scripted provider answers each call from a list, so no test touches the network (rule 16).
"""

import ast
import base64
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from google.genai import errors

from app.ai import pipeline
from app.ai.gemini import GeminiProvider
from app.ai.pipeline import PASSED, SKIPPED, PipelineRequest, run_pipeline
from app.ai.prompts import (
    PROMPT_VERSION,
    NoEvidence,
    PdfEvidence,
    PromptContext,
    TextEvidence,
    TopicEvidence,
)
from app.ai.provider import (
    AIRateLimited,
    AITransient,
    AIUnavailable,
    Attachment,
    CardDraft,
    Prompt,
    TokenUsage,
    verdicts_schema,
)
from app.api.generate import _evidence
from app.models import AiGeneration

ORIGINAL = Prompt(system="rules", text="write cards", max_cards=2)


def card(n, back=None):
    return {"front": f"Question {n}?", "back": back or f"Answer {n}"}


def ok(*indexes):
    return [{"index": index, "ok": True} for index in indexes]


def bad(index, reason="Wrong."):
    return {"index": index, "ok": False, "reason": reason}


class Scripted:
    """Answers each call with the next item in `replies`. An exception in the list is raised."""

    name = "scripted"

    def __init__(self, *replies):
        self.replies = list(replies)
        self.prompts = []

    def _next(self, prompt):
        self.prompts.append(prompt)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    generate_cards = _next
    judge_cards = _next


class ExtractingWriter(Scripted):
    """Scripted, with extract replies keyed by chunk, because extract calls run in parallel."""

    def __init__(self, facts, *replies):
        super().__init__(*replies)
        self.facts = facts
        self.chunks_seen = []

    def extract_facts(self, prompt):
        chunk = next(chunk for chunk in self.facts if chunk in prompt.text)
        self.chunks_seen.append(chunk)
        reply = self.facts[chunk]
        if isinstance(reply, Exception):
            raise reply
        return reply


def run(writer, judge, count=2, deck_name="Deck", chunks=(), file_text="", evidence=None, **kwargs):
    context = PromptContext("file", count, deck_name, None)
    if evidence is None:
        evidence = TextEvidence(file_text, chunks) if chunks or file_text else NoEvidence()
    request = PipelineRequest(
        prompt=ORIGINAL, context=context, existing_fronts=[], evidence=evidence, **kwargs
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
    assert repair.max_cards == 1
    assert "The back is wrong." in repair.text
    assert '"front": "Question 1?"' in repair.text.split("<kept_cards>")[-1]
    assert judge.prompts[1].max_cards == 1
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
        provider.generate_cards(ORIGINAL)

    assert type(caught.value) is expected


def test_each_chunk_is_extracted_and_the_writer_gets_the_merged_facts():
    writer = ExtractingWriter(
        {"part one": ["Fact one."], "part two": ["Fact two."]}, [card(1), card(2)]
    )
    judge = Scripted(ok(0, 1))

    result = run(
        writer, judge, chunks=["part one", "part two"], file_text="part one part two",
        deck_name="Biology",
    )

    assert sorted(writer.chunks_seen) == ["part one", "part two"]
    assert "<source>\nFact one.\nFact two.\n</source>" in writer.prompts[0].text
    assert "Deck name: Biology" in writer.prompts[0].text
    assert "part one part two" in judge.prompts[0].text
    assert fronts(result) == ["Question 1?", "Question 2?"]
    assert result.model_calls == 4


def test_merged_facts_keep_document_order_and_drop_duplicates():
    writer = ExtractingWriter(
        {"one": ["B fact.", "Shared fact."], "two": ["shared fact", "A fact."]}, [card(1)]
    )
    run(writer, Scripted(ok(0)), count=1, chunks=["one", "two"])
    assert "<source>\nB fact.\nShared fact.\nA fact.\n</source>" in writer.prompts[0].text


def test_a_failed_chunk_doesnt_stop_the_others():
    writer = ExtractingWriter({"one": AIUnavailable(), "two": ["Fact two."]}, [card(1)])
    result = run(writer, Scripted(ok(0)), count=1, chunks=["one", "two"])
    assert "<source>\nFact two.\n</source>" in writer.prompts[0].text
    assert fronts(result) == ["Question 1?"]
    assert result.model_calls == 4


def test_a_rate_limited_chunk_ends_the_run_before_generate():
    writer = ExtractingWriter({"one": AIRateLimited(), "two": ["Fact two."]}, [card(1)])
    with pytest.raises(AIRateLimited):
        run(writer, Scripted(ok(0)), count=1, chunks=["one", "two"])
    assert writer.prompts == []


def test_the_whole_document_is_used_when_no_chunk_yields_facts():
    writer = ExtractingWriter({"one": AIUnavailable(), "two": []}, [card(1)])
    run(writer, Scripted(ok(0)), count=1, chunks=["one", "two"])
    assert writer.prompts[0] is ORIGINAL


def test_a_repair_uses_the_merged_facts():
    writer = ExtractingWriter({"one": ["Fact one."]}, [card(1)], [card(2)])
    run(writer, Scripted([bad(0)], ok(0)), count=1, chunks=["one"])
    assert "<source>\nFact one.\n</source>" in writer.prompts[1].text


def test_a_short_document_skips_the_extract_step():
    writer = ExtractingWriter({"one": ["Fact one."]}, [card(1)])
    run(writer, Scripted(ok(0)), count=1)
    assert writer.chunks_seen == []
    assert writer.prompts[0] is ORIGINAL


def test_the_judge_gets_a_topic_as_a_topic_not_a_source():
    judge = Scripted(ok(0))
    run(Scripted([card(1)]), judge, count=1, evidence=TopicEvidence("Cells"))
    assert "<topic>\nCells\n</topic>" in judge.prompts[0].text
    assert "<source>" not in judge.prompts[0].text


def test_the_judge_gets_a_pdf_as_an_attachment():
    pdf = Attachment(mime_type="application/pdf", data=b"%PDF-")
    judge = Scripted(ok(0))
    run(Scripted([card(1)]), judge, count=1, evidence=PdfEvidence(pdf))
    assert judge.prompts[0].attachment is pdf
    assert "<source>" not in judge.prompts[0].text


def test_the_judge_gets_no_material_without_evidence():
    judge = Scripted(ok(0))
    run(Scripted([card(1)]), judge, count=1)
    assert judge.prompts[0].attachment is None
    assert "<source>" not in judge.prompts[0].text
    assert "<topic>" not in judge.prompts[0].text


def test_each_mode_maps_to_its_evidence():
    pdf = Attachment(mime_type="application/pdf", data=b"%PDF-")
    assert _evidence("Cells", None, None, []) == TopicEvidence("Cells")
    assert _evidence(None, "notes", None, ["a"]) == TextEvidence("notes", ["a"])
    assert _evidence(None, None, pdf, []) == PdfEvidence(pdf)
    assert _evidence(None, None, None, []) == NoEvidence()


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


def test_gemini_judge_cards_asks_for_verdicts_and_reads_them():
    reply = SimpleNamespace(
        text=json.dumps({"verdicts": ok(0)}), prompt_feedback=None, candidates=[]
    )
    calls = []

    def generate_content(**kwargs):
        calls.append(kwargs)
        return reply

    client = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    provider = GeminiProvider("key", "lite", client=client)

    assert provider.judge_cards(Prompt(system="s", text="t", max_cards=3)) == ok(0)
    assert calls[0]["model"] == "lite"
    assert calls[0]["config"].response_json_schema == verdicts_schema(3)


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

    provider.generate_cards(ORIGINAL)
    provider.generate_cards(ORIGINAL)

    assert provider.usage == TokenUsage(input_tokens=200, output_tokens=50)


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

    provider.generate_cards(ORIGINAL)

    assert provider.usage == TokenUsage()


@pytest.fixture
def me(make_user, login_as):
    user = make_user(email="me@example.com")
    login_as(user)
    return user


@pytest.fixture
def deck(me, make_deck):
    return make_deck(me, name="Biology", description="Cells and more")


@pytest.fixture
def graph_mode(app, monkeypatch):
    monkeypatch.setitem(app.config, "AI_PIPELINE", "graph")


def _post(client, deck_id):
    return client.post(
        f"/api/decks/{deck_id}/generate", json={"mode": "prompt", "count": 2, "prompt": "cells"}
    )


def _spent(db, me, deck, calls, empty=False):
    db.session.add(
        AiGeneration(
            user_id=me.id, deck_id=deck.id, mode="prompt", requested_count=1, model="fake",
            model_calls=calls, empty=empty, candidates=[],
        )
    )
    db.session.commit()


def test_the_route_saves_the_prompt_version_and_token_counts(client, deck):
    assert _post(client, deck.id).status_code == 201
    saved = AiGeneration.query.one()
    assert saved.prompt_version == PROMPT_VERSION
    assert (saved.input_tokens, saved.output_tokens) == (0, 0)
    assert saved.judge_model is None
    assert saved.judge_input_tokens is None


def test_the_graph_saves_the_judges_model_and_tokens(client, app, deck, graph_mode):
    assert _post(client, deck.id).status_code == 201
    saved = AiGeneration.query.one()
    assert saved.judge_model == "fake"
    assert (saved.judge_input_tokens, saved.judge_output_tokens) == (0, 0)


def test_empty_batches_dont_use_the_learners_cap(client, db, me, deck):
    for _ in range(10):
        _spent(db, me, deck, 1, empty=True)
    assert _post(client, deck.id).status_code == 201


def test_batches_with_cards_still_use_the_learners_cap(client, db, me, deck):
    for _ in range(10):
        _spent(db, me, deck, 1)
    assert _post(client, deck.id).status_code == 429


def test_empty_batches_still_count_toward_the_site_cap(client, db, me, deck):
    _spent(db, me, deck, 18, empty=True)
    assert _post(client, deck.id).status_code == 429


def test_the_route_runs_the_graph_and_saves_what_it_spent(client, deck, graph_mode):
    resp = _post(client, deck.id)
    assert resp.status_code == 201
    assert resp.get_json()["verification"] == PASSED
    assert len(resp.get_json()["cards"]) == 2
    saved = AiGeneration.query.one()
    assert saved.model_calls == 2


def test_the_route_stays_on_one_call_without_the_flag(client, deck):
    resp = _post(client, deck.id)
    assert resp.status_code == 201
    assert resp.get_json()["verification"] is None
    assert AiGeneration.query.one().model_calls == 1


def _post_long_file(client, deck_id):
    data = base64.b64encode(("word " * 6000).encode()).decode()
    return client.post(
        f"/api/decks/{deck_id}/generate",
        json={
            "mode": "file",
            "count": 2,
            "file": {"name": "notes.txt", "mime_type": "text/plain", "data": data},
        },
    )


def test_the_route_extracts_a_long_file_and_saves_the_calls(client, deck, graph_mode):
    resp = _post_long_file(client, deck.id)
    assert resp.status_code == 201
    assert len(resp.get_json()["cards"]) == 2
    assert AiGeneration.query.one().model_calls == 4


def test_the_site_cap_reserves_a_call_per_chunk(client, db, me, deck, graph_mode):
    _spent(db, me, deck, 12)
    assert _post(client, deck.id).status_code == 201
    AiGeneration.query.filter(AiGeneration.model_calls != 12).delete()
    db.session.commit()
    assert _post_long_file(client, deck.id).status_code == 429


def test_the_site_cap_keeps_room_for_the_graphs_worst_case(client, db, me, deck, graph_mode):
    _spent(db, me, deck, 15)
    assert _post(client, deck.id).status_code == 429


def test_the_same_spend_still_allows_a_single_call(client, db, me, deck):
    _spent(db, me, deck, 15)
    assert _post(client, deck.id).status_code == 201
