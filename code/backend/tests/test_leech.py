"""Leech Doctor: the graph's pause and resume, the background job, and the routes.

Route tests use the database under test, so the Postgres CI job exercises PostgresSaver.
`TestConfig` runs jobs inline, so a request's job has finished when the response arrives.
"""

import json
import uuid
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from app.ai.checkpoints import discard_threads
from app.ai.fake import FakeProvider
from app.ai.gemini import GeminiProvider
from app.ai.leech import MAX_CARDS_PER_REVIEW, resume_review, similar_cards, start_review
from app.ai.prompts import escape_tags
from app.ai.provider import AIRateLimited, AIUnavailable, Prompt, fixes_schema
from app.leech_jobs import (
    MAX_CONCURRENT_JOBS,
    RETRY_AFTER,
    _job_slots,
    _start_thread,
    run_job,
)
from app.models import AiGeneration, Card, LeechReview, utcnow


def leech(card_id=1, front="Question one?", back="Answer one"):
    return {"id": card_id, "front": front, "back": back, "lapses": 5, "similar": []}


def option(kind="rewrite", cards=None):
    return {
        "kind": kind,
        "reason": "It is vague.",
        "cards": cards or [{"front": "Better question?", "back": "Better answer"}],
    }


def reply(*options_per_card, shared_cause=None):
    return {
        "shared_cause": shared_cause,
        "recommendations": [
            {"index": index, "options": options} for index, options in enumerate(options_per_card)
        ],
    }


class Scripted:
    """Answers each call with the next reply, or raises it if it is an exception."""

    name = "scripted"

    def __init__(self, *replies):
        self.replies = list(replies)
        self.usage = SimpleNamespace(input_tokens=10, output_tokens=5)
        self.prompts = []

    def recommend_fixes(self, prompt):
        self.prompts.append(prompt)
        answer = self.replies.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


class ScriptedJudge:
    """Answers with `verdicts`, or raises it if it is an exception."""

    name = "judge"

    def __init__(self, verdicts):
        self.verdicts = verdicts
        self.usage = SimpleNamespace(input_tokens=7, output_tokens=3)
        self.prompts = []

    def judge_cards(self, prompt):
        self.prompts.append(prompt)
        if isinstance(self.verdicts, Exception):
            raise self.verdicts
        return self.verdicts


def start(answer, cards, existing=(), checkpointer=None, judge=None):
    checkpointer = checkpointer or InMemorySaver()
    thread_id = str(uuid.uuid4())
    provider = Scripted(answer)
    judge = judge or FakeProvider()
    outcome = start_review(provider, judge, checkpointer, thread_id, cards, list(existing))
    return outcome, checkpointer, thread_id, provider


def two_cards():
    return [leech(1), leech(2, "Question two?", "Answer two")]


def second_option():
    return option(cards=[{"front": "Second question?", "back": "Second answer"}])


def test_one_call_covers_every_card_and_the_run_pauses():
    outcome, _, _, provider = start(reply([option()], [second_option()]), two_cards())
    assert [item["card_id"] for item in outcome.recommendations] == [1, 2]
    assert outcome.recommendations[0]["lapses"] == 5
    assert outcome.model_calls == 2
    assert outcome.verification == "passed"
    assert len(provider.prompts) == 1
    assert "Question one?" in provider.prompts[0].text
    assert "Question two?" in provider.prompts[0].text


def test_a_new_graph_can_resume_from_the_checkpoint():
    _, checkpointer, thread_id, _ = start(reply([option()]), [leech()])
    decisions = [{"card_id": 1, "option": 0}]
    assert resume_review(checkpointer, thread_id, decisions) == decisions


def test_the_checkpoint_doesnt_save_the_inputs_or_providers():
    _, checkpointer, thread_id, _ = start(reply([option()]), [leech()], ["Secret deck front?"])
    saved = checkpointer.get_tuple({"configurable": {"thread_id": thread_id}})
    values = saved.checkpoint["channel_values"]
    assert "existing_fronts" not in values
    assert "cards" not in values
    assert "Secret deck front?" not in str(values)


def test_the_judge_checks_every_new_card_in_one_call():
    judge = ScriptedJudge([{"index": 0, "ok": True}, {"index": 1, "ok": True}])
    start(reply([option()], [second_option()]), two_cards(), judge=judge)
    assert len(judge.prompts) == 1
    assert judge.prompts[0].max_cards == 2
    assert "Better question?" in judge.prompts[0].text
    assert "Second question?" in judge.prompts[0].text


def test_an_option_is_dropped_if_any_of_its_cards_fails():
    split = option("split", cards=[
        {"front": "Part one?", "back": "Alpha"}, {"front": "Part two?", "back": "Beta"},
    ])
    contrast = option("contrast", cards=[{"front": "Which one?", "back": "This"}])
    judge = ScriptedJudge([
        {"index": 0, "ok": True}, {"index": 1, "ok": False}, {"index": 2, "ok": True},
    ])

    outcome, *_ = start(reply([split, contrast]), [leech()], judge=judge)

    assert [item["kind"] for item in outcome.recommendations[0]["options"]] == ["contrast"]


def test_a_missing_verdict_counts_as_a_failure():
    judge = ScriptedJudge([{"index": 0, "ok": True}])
    outcome, *_ = start(reply([option()], [second_option()]), two_cards(), judge=judge)
    assert [item["card_id"] for item in outcome.recommendations] == [1]


def test_a_card_with_no_approved_options_gets_no_recommendation():
    judge = ScriptedJudge([{"index": 0, "ok": False}])
    outcome, *_ = start(reply([option()]), [leech()], judge=judge)
    assert outcome.recommendations == []
    assert outcome.verification == "passed"


def test_a_shared_cause_is_dropped_if_the_judge_leaves_one_card():
    judge = ScriptedJudge([{"index": 0, "ok": True}, {"index": 1, "ok": False}])
    answer = reply([option()], [second_option()], shared_cause="Same topic.")
    outcome, *_ = start(answer, two_cards(), judge=judge)
    assert outcome.shared_cause is None


@pytest.mark.parametrize("failure", [AIRateLimited(), AIUnavailable(), [], ["junk"]])
def test_when_the_judge_cant_answer_the_options_stay_and_say_so(failure):
    outcome, *_ = start(reply([option()]), [leech()], judge=ScriptedJudge(failure))
    assert len(outcome.recommendations) == 1
    assert outcome.verification == "skipped"
    assert outcome.failed is False
    assert outcome.model_calls == 2


def test_nothing_to_check_skips_the_judge():
    judge = ScriptedJudge([])
    outcome, *_ = start(reply([]), [leech()], judge=judge)
    assert judge.prompts == []
    assert outcome.model_calls == 1


def test_a_failed_diagnosis_skips_the_judge():
    judge = ScriptedJudge([])
    start(AIUnavailable(), [leech()], judge=judge)
    assert judge.prompts == []


def test_a_shared_cause_needs_two_recommendations():
    answer = reply([option()], [second_option()], shared_cause=" Same topic. ")
    both, *_ = start(answer, two_cards())
    assert both.shared_cause == "Same topic."
    one, *_ = start(reply([option()], [], shared_cause="Same topic."), two_cards())
    assert one.shared_cause is None


@pytest.mark.parametrize("failure", [AIRateLimited(), AIUnavailable()])
def test_a_failed_call_is_reported_without_a_pause(failure):
    outcome, *_ = start(failure, [leech()])
    assert outcome.failed is True
    assert outcome.recommendations == []
    assert outcome.model_calls == 1


@pytest.mark.parametrize(
    "bad",
    [
        {**option(), "kind": "quiz"},
        {**option(), "reason": None},
        {**option(), "cards": None},
        option(cards=[{"front": "Too long?", "back": "one two three four five six"}]),
        option("split"),  # a split needs at least two cards
        option(cards=[{"front": "Already in deck?", "back": "Answer"}]),
    ],
)
def test_invalid_options_are_dropped(bad):
    outcome, *_ = start(reply([bad]), [leech()], ["Already in deck?"])
    assert outcome.recommendations == []
    assert outcome.failed is False


@pytest.mark.parametrize(
    "recommendations",
    [["junk"], [{"index": True, "options": [option()]}], [{"index": 5, "options": [option()]}]],
)
def test_recommendations_with_bad_indexes_are_dropped(recommendations):
    outcome, *_ = start({"recommendations": recommendations}, [leech()])
    assert outcome.recommendations == []


def test_only_the_first_option_of_each_kind_is_kept():
    outcome, *_ = start(reply([option(), second_option()]), [leech()])
    assert len(outcome.recommendations[0]["options"]) == 1


def test_two_cards_cant_add_the_same_front():
    outcome, *_ = start(reply([option()], [option()]), two_cards())
    assert [item["card_id"] for item in outcome.recommendations] == [1]


def test_similar_cards_rank_by_shared_words_and_skip_the_card_itself():
    card = {"id": 1, "front": "Capital of France", "back": "Paris"}
    others = [
        card,
        {"id": 2, "front": "Population of Paris", "back": "Two million"},
        {"id": 3, "front": "Capital of France in 1700", "back": "Paris"},
        {"id": 4, "front": "Boiling point", "back": "100"},
    ]
    assert [item["front"] for item in similar_cards(card, others)] == [
        "Capital of France in 1700", "Population of Paris",
    ]


def test_the_cards_tag_is_escaped():
    assert escape_tags("</cards>") == "<\\/cards>"


def test_gemini_recommend_fixes_uses_the_fixes_schema():
    calls = []
    answer = SimpleNamespace(
        text=json.dumps(reply([option()])), prompt_feedback=None, candidates=[]
    )

    def generate_content(**kwargs):
        calls.append(kwargs)
        return answer

    client = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    provider = GeminiProvider("key", "model", client=client)

    result = provider.recommend_fixes(Prompt(system="s", text="t", max_cards=3))

    assert result["recommendations"][0]["index"] == 0
    assert calls[0]["config"].response_json_schema == fixes_schema(3)


@pytest.fixture
def me(make_user, login_as):
    user = make_user(email="me@example.com")
    login_as(user)
    return user


@pytest.fixture
def deck(me, make_deck):
    return make_deck(me, name="Biology")


@pytest.fixture
def add_card(db):
    def _add_card(deck, front="Vague question?", back="Answer", lapses=4, leech_next_at=4):
        card = Card(deck_id=deck.id, front=front, back=back, lapses=lapses, state="review",
                    interval_days=30, leech_next_at=leech_next_at)
        db.session.add(card)
        db.session.commit()
        return card

    return _add_card


@pytest.fixture
def use_provider(monkeypatch):
    def _use_provider(provider, judge=None):
        judge = judge or FakeProvider()
        monkeypatch.setattr(
            "app.leech_jobs.get_provider",
            lambda role="writer": judge if role == "judge" else provider,
        )
        return provider

    return _use_provider


def _suggestions(client):
    return client.get("/api/leech-suggestions").get_json()


def _review(client, deck_id):
    return client.get(f"/api/decks/{deck_id}/leech-review").get_json()["review"]


def _decide(client, review_id, decisions):
    return client.post(f"/api/leech-reviews/{review_id}/decisions", json={"decisions": decisions})


def test_nothing_flagged_makes_no_review(client, deck, add_card):
    add_card(deck, lapses=3)
    assert _suggestions(client) == {"processing": False, "ready": []}
    assert LeechReview.query.count() == 0


def test_a_flagged_card_produces_a_checked_suggestion(client, deck, add_card):
    add_card(deck)

    body = _suggestions(client)

    assert body["processing"] is False
    assert body["ready"] == [{
        "review_id": LeechReview.query.one().id,
        "deck_id": deck.id,
        "deck_name": "Biology",
        "card_count": 1,
    }]
    saved = LeechReview.query.one()
    assert (saved.status, saved.model_calls, saved.attempts) == ("pending", 2, 1)
    assert (saved.verification, saved.judge_model) == ("passed", "fake")


def test_the_judges_tokens_are_saved_apart_from_the_writers(
    client, deck, add_card, use_provider
):
    add_card(deck)
    judge = ScriptedJudge([{"index": 0, "ok": True}])
    use_provider(Scripted(reply([option()])), judge)

    _suggestions(client)

    saved = LeechReview.query.one()
    assert (saved.input_tokens, saved.output_tokens) == (10, 5)
    assert (saved.judge_model, saved.judge_input_tokens, saved.judge_output_tokens) == (
        "judge", 7, 3,
    )


def test_a_skipped_check_reaches_the_review(client, deck, add_card, use_provider):
    add_card(deck)
    use_provider(Scripted(reply([option()])), ScriptedJudge(AIUnavailable()))

    _suggestions(client)

    assert _review(client, deck.id)["verification"] == "skipped"


def test_two_calls_cover_up_to_the_limit_of_cards(client, deck, add_card):
    for n in range(MAX_CARDS_PER_REVIEW + 2):
        add_card(deck, front=f"Question {n}?")

    assert _suggestions(client)["ready"][0]["card_count"] == MAX_CARDS_PER_REVIEW
    assert LeechReview.query.one().model_calls == 2


def test_checking_again_doesnt_spend_again(client, deck, add_card):
    add_card(deck)
    _suggestions(client)
    _suggestions(client)
    assert LeechReview.query.one().model_calls == 2


def test_only_your_own_suggestions_are_listed(client, me, make_user, make_deck, add_card):
    other = make_deck(make_user(email="other@example.com"))
    add_card(other)
    assert _suggestions(client)["ready"] == []
    assert LeechReview.query.count() == 0


def _retry_due(db):
    """Move the queued review past its retry wait."""
    LeechReview.query.one().started_at = utcnow() - RETRY_AFTER - timedelta(minutes=1)
    db.session.commit()


def test_a_failed_call_retries_once_then_fails_and_stops_flagging(
    client, db, deck, add_card, use_provider
):
    card = add_card(deck)
    use_provider(Scripted(AIUnavailable(), AIUnavailable()))

    first = _suggestions(client)
    saved = LeechReview.query.one()
    assert (saved.status, saved.attempts, first["processing"]) == ("queued", 1, False)

    _retry_due(db)
    second = _suggestions(client)
    db.session.refresh(saved)
    assert (saved.status, saved.attempts, saved.model_calls) == ("failed", 2, 2)
    assert second["processing"] is False
    assert db.session.get(Card, card.id).leech_next_at == 6


def test_a_retry_waits_for_the_retry_time(client, deck, add_card, use_provider):
    add_card(deck)
    provider = use_provider(Scripted(AIUnavailable(), reply([option()])))

    _suggestions(client)
    _suggestions(client)

    assert len(provider.prompts) == 1


def test_a_retry_can_succeed(client, db, deck, add_card, use_provider):
    add_card(deck)
    use_provider(Scripted(AIUnavailable(), reply([option()])))

    _suggestions(client)
    _retry_due(db)
    body = _suggestions(client)

    assert len(body["ready"]) == 1
    assert LeechReview.query.one().model_calls == 3


def test_rate_limits_wait_without_using_an_attempt(client, db, deck, add_card, use_provider):
    card = add_card(deck)
    use_provider(Scripted(AIRateLimited(), AIRateLimited(), reply([option()])))

    for _ in range(2):
        body = _suggestions(client)
        saved = LeechReview.query.one()
        assert (saved.status, saved.attempts, body["processing"]) == ("queued", 0, False)
        assert db.session.get(Card, card.id).leech_next_at == 4
        _retry_due(db)

    assert len(_suggestions(client)["ready"]) == 1


def test_turning_it_off_stops_new_jobs(client, app, deck, add_card):
    app.config["AI_LEECH_ENABLED"] = False
    add_card(deck)

    assert _suggestions(client) == {"processing": False, "ready": []}
    assert LeechReview.query.count() == 0


def test_turning_it_off_keeps_pending_suggestions(client, app, deck, add_card):
    add_card(deck)
    _suggestions(client)
    app.config["AI_LEECH_ENABLED"] = False

    assert len(_suggestions(client)["ready"]) == 1


def test_jobs_leave_the_reserve_for_generating_cards(client, db, me, deck, add_card):
    db.session.add(AiGeneration(
        user_id=me.id, deck_id=deck.id, mode="prompt", requested_count=1, model="fake",
        model_calls=9, candidates=[],
    ))
    db.session.commit()
    add_card(deck)

    assert _suggestions(client) == {"processing": False, "ready": []}
    resp = client.post(
        f"/api/decks/{deck.id}/generate", json={"mode": "prompt", "count": 1, "prompt": "Cells"}
    )
    assert resp.status_code == 201


def test_the_learner_limit_reserves_room_for_both_calls(client, db, me, deck, add_card, make_deck):
    db.session.add(LeechReview(
        user_id=me.id, deck_id=make_deck(me, name="Old").id, status="failed", model_calls=3,
        recommendations=[],
    ))
    db.session.commit()
    add_card(deck)

    assert _suggestions(client) == {"processing": False, "ready": []}


def test_another_learners_spending_doesnt_use_your_limit(
    client, db, me, deck, add_card, make_user, make_deck
):
    other = make_user(email="other@example.com")
    db.session.add(LeechReview(
        user_id=other.id, deck_id=make_deck(other).id, status="failed", model_calls=3,
        recommendations=[],
    ))
    db.session.commit()
    add_card(deck)

    assert len(_suggestions(client)["ready"]) == 1


def test_a_full_worker_leaves_the_job_queued(app):
    app.config["AI_LEECH_RUN_INLINE"] = False
    slots = [_job_slots.acquire(blocking=False) for _ in range(MAX_CONCURRENT_JOBS)]
    try:
        with patch("app.leech_jobs.threading.Thread") as thread:
            _start_thread(1)
        thread.assert_not_called()
    finally:
        for taken in slots:
            if taken:
                _job_slots.release()


def test_a_failed_job_discards_its_checkpoint(client, deck, add_card, use_provider, monkeypatch):
    add_card(deck)
    use_provider(Scripted(AIUnavailable()))
    discarded = []
    monkeypatch.setattr("app.leech_jobs.discard_threads", lambda url, ids: discarded.extend(ids))

    _suggestions(client)

    assert discarded == [LeechReview.query.one().thread_id]


def test_a_paused_job_keeps_its_checkpoint(client, deck, add_card, monkeypatch):
    add_card(deck)
    discarded = []
    monkeypatch.setattr("app.leech_jobs.discard_threads", lambda url, ids: discarded.extend(ids))

    _suggestions(client)

    assert discarded == []


def test_deleting_a_deck_discards_its_checkpoints(client, deck, add_card, monkeypatch):
    add_card(deck)
    _suggestions(client)
    thread_id = LeechReview.query.one().thread_id
    discarded = []
    monkeypatch.setattr("app.api.decks.discard_threads", lambda url, ids: discarded.extend(ids))

    resp = client.delete(f"/api/decks/{deck.id}")

    assert resp.status_code == 204
    assert discarded == [thread_id]


def test_a_failed_discard_is_harmless(app):
    with patch("app.ai.checkpoints.open_checkpointer", side_effect=RuntimeError("down")):
        discard_threads("postgresql://nowhere", ["thread"])


def test_a_failed_resume_still_applies_the_decisions(client, deck, add_card, monkeypatch):
    card = add_card(deck)
    _suggestions(client)
    review = _review(client, deck.id)

    def fail(*args):
        raise RuntimeError("down")

    monkeypatch.setattr("app.api.leeches.resume_review", fail)

    assert _decide(client, review["id"], [{"card_id": card.id, "option": None}]).status_code == 200
    assert LeechReview.query.one().status == "completed"


def test_a_failed_commit_leaves_the_review_ready_to_retry(client, db, deck, add_card, monkeypatch):
    card = add_card(deck)
    card_id = card.id
    _suggestions(client)
    review = _review(client, deck.id)
    resumed = []
    monkeypatch.setattr("app.api.leeches.resume_review", lambda *args: resumed.append(args))

    with patch.object(db.session, "commit", side_effect=RuntimeError("down")):
        resp = _decide(client, review["id"], [{"card_id": card_id, "option": None}])
    db.session.rollback()

    assert resp.status_code == 500
    assert resumed == []
    assert LeechReview.query.one().status == "pending"


def test_an_unexpected_error_counts_as_a_failure(client, deck, add_card, monkeypatch):
    add_card(deck)
    monkeypatch.setattr("app.leech_jobs.start_review", lambda *args: 1 / 0)

    _suggestions(client)

    assert LeechReview.query.one().status == "queued"


def test_cards_with_no_usable_fix_stop_flagging(client, db, deck, add_card, use_provider):
    card = add_card(deck, lapses=5, leech_next_at=4)
    use_provider(Scripted(reply([])))

    assert _suggestions(client)["ready"] == []

    assert LeechReview.query.one().status == "completed"
    assert db.session.get(Card, card.id).leech_next_at == 7


def test_a_card_without_a_fix_stops_flagging_while_the_other_waits(
    client, db, deck, add_card, use_provider
):
    fixed = add_card(deck, front="One?", lapses=6)
    unfixed = add_card(deck, front="Two?", lapses=5)
    use_provider(Scripted(reply([option()], [])))

    _suggestions(client)

    assert db.session.get(Card, fixed.id).leech_next_at == 4
    assert db.session.get(Card, unfixed.id).leech_next_at == 7


def test_the_leech_budget_makes_jobs_wait(client, app, db, me, deck, add_card):
    app.config["AI_LEECH_DAILY_LIMIT"] = 1
    db.session.add(LeechReview(
        user_id=me.id, deck_id=deck.id, status="failed", model_calls=1, recommendations=[],
    ))
    db.session.commit()
    add_card(deck)

    body = _suggestions(client)

    assert body == {"processing": False, "ready": []}
    assert LeechReview.query.filter_by(status="queued").count() == 1


def test_the_site_cap_makes_jobs_wait(client, db, me, deck, add_card):
    db.session.add(AiGeneration(
        user_id=me.id, deck_id=deck.id, mode="prompt", requested_count=1, model="fake",
        model_calls=18, candidates=[],
    ))
    db.session.commit()
    add_card(deck)

    assert _suggestions(client) == {"processing": False, "ready": []}


def test_reviews_count_toward_the_generate_routes_site_cap(client, db, me, deck):
    db.session.add(LeechReview(
        user_id=me.id, deck_id=deck.id, status="completed", model_calls=18, recommendations=[],
    ))
    db.session.commit()

    resp = client.post(
        f"/api/decks/{deck.id}/generate", json={"mode": "prompt", "count": 1, "prompt": "Cells"}
    )

    assert resp.status_code == 429


def test_a_missing_key_leaves_the_job_queued(client, app, deck, add_card):
    app.config["AI_WRITER_PROVIDER"] = "gemini"
    app.config["GEMINI_API_KEY"] = ""
    add_card(deck)

    assert _suggestions(client) == {"processing": False, "ready": []}
    assert LeechReview.query.one().attempts == 0


def test_a_lost_job_is_restarted(client, db, me, deck, add_card):
    add_card(deck)
    db.session.add(LeechReview(
        user_id=me.id, deck_id=deck.id, status="running", attempts=1,
        started_at=utcnow() - timedelta(minutes=6), recommendations=[],
    ))
    db.session.commit()

    assert len(_suggestions(client)["ready"]) == 1


def test_a_running_job_isnt_started_twice(client, db, me, deck, add_card):
    add_card(deck)
    review = LeechReview(
        user_id=me.id, deck_id=deck.id, status="running", attempts=1, started_at=utcnow(),
        recommendations=[],
    )
    db.session.add(review)
    db.session.commit()

    assert _suggestions(client) == {"processing": True, "ready": []}
    run_job(review.id)
    assert LeechReview.query.one().attempts == 1


def test_a_lost_job_on_its_last_attempt_fails(client, db, me, deck, add_card):
    add_card(deck)
    review = LeechReview(
        user_id=me.id, deck_id=deck.id, status="running", attempts=2,
        started_at=utcnow() - timedelta(minutes=6), recommendations=[],
    )
    db.session.add(review)
    db.session.commit()

    run_job(review.id)

    assert db.session.get(LeechReview, review.id).status == "failed"


def test_outside_tests_a_job_runs_in_a_thread(app):
    app.config["AI_LEECH_RUN_INLINE"] = False
    with patch("app.leech_jobs.threading.Thread") as thread:
        _start_thread(1)
    thread.return_value.start.assert_called_once()
    _job_slots.release()  # the fake thread never ran, so nothing released its slot


def test_someone_elses_deck_review_is_404(client, me, make_user, make_deck):
    other = make_deck(make_user(email="other@example.com"))
    assert client.get(f"/api/decks/{other.id}/leech-review").status_code == 404


def test_a_deck_with_no_pending_review_returns_null(client, deck):
    assert _review(client, deck.id) is None


def test_the_review_includes_the_shared_cause(client, deck, add_card):
    add_card(deck, front="One?")
    add_card(deck, front="Two?")
    _suggestions(client)

    assert _review(client, deck.id)["shared_cause"] == "Sample shared cause."


def test_a_rewrite_replaces_the_card_and_starts_a_new_schedule(client, deck, add_card):
    card = add_card(deck)
    card_id = card.id
    _suggestions(client)
    review = _review(client, deck.id)

    resp = _decide(client, review["id"], [{"card_id": card_id, "option": 0}])

    assert resp.status_code == 200
    assert Card.query.filter_by(id=card_id).first() is None
    new_card = Card.query.one()
    assert (new_card.state, new_card.lapses, new_card.origin) == ("new", 0, "ai")
    assert new_card.leech_next_at == 4
    saved = LeechReview.query.one()
    assert saved.status == "completed"
    assert saved.decisions == [
        {"card_id": card_id, "kind": "rewrite", "new_card_ids": [new_card.id]}
    ]
    assert saved.recommendations[0]["lapses"] == 4
    assert _suggestions(client)["ready"] == []


def test_keeping_a_card_reflags_it_after_two_more_lapses(client, db, deck, add_card):
    card = add_card(deck)
    _suggestions(client)
    review = _review(client, deck.id)

    assert _decide(client, review["id"], [{"card_id": card.id, "option": None}]).status_code == 200

    saved = db.session.get(Card, card.id)
    assert saved.leech_next_at == 6
    assert LeechReview.query.count() == 1
    assert _suggestions(client)["ready"] == []

    # The 7-day pause applies, because every decision was to keep the card.
    saved.lapses = 6
    db.session.commit()
    assert _suggestions(client)["ready"] == []
    assert LeechReview.query.count() == 1


def test_a_kept_card_is_flagged_again_after_the_pause(client, db, deck, add_card):
    card = add_card(deck)
    _suggestions(client)
    review = _review(client, deck.id)
    _decide(client, review["id"], [{"card_id": card.id, "option": None}])
    saved = db.session.get(Card, card.id)
    saved.lapses = 6
    LeechReview.query.one().completed_at = utcnow() - timedelta(days=8)
    db.session.commit()

    assert len(_suggestions(client)["ready"]) == 1


def test_acting_on_a_card_doesnt_start_the_pause(client, db, deck, add_card):
    keep = add_card(deck, front="Keep?")
    rewrite = add_card(deck, front="Rewrite?")
    _suggestions(client)
    review = _review(client, deck.id)
    _decide(client, review["id"], [
        {"card_id": keep.id, "option": None}, {"card_id": rewrite.id, "option": 0},
    ])
    saved = db.session.get(Card, keep.id)
    saved.lapses = 6
    db.session.commit()

    assert len(_suggestions(client)["ready"]) == 1


def test_removing_deletes_the_card_and_adds_nothing(client, deck, add_card):
    card = add_card(deck)
    card_id = card.id
    _suggestions(client)
    review = _review(client, deck.id)

    resp = _decide(client, review["id"], [{"card_id": card_id, "option": "remove"}])

    assert resp.status_code == 200
    assert Card.query.count() == 0
    assert LeechReview.query.one().decisions[0]["kind"] == "remove"


def test_a_contrast_adds_cards_and_keeps_the_original(client, db, deck, add_card, use_provider):
    card = add_card(deck)
    use_provider(Scripted(reply([option("contrast")])))
    _suggestions(client)
    review = _review(client, deck.id)

    assert _decide(client, review["id"], [{"card_id": card.id, "option": 0}]).status_code == 200

    assert Card.query.count() == 2
    assert db.session.get(Card, card.id).leech_next_at == 6


@pytest.mark.parametrize(
    "decisions",
    [
        "junk",
        [],
        ["junk"],
        [{"card_id": 999999, "option": 0}],
        [{"card_id": [], "option": 0}],
        [{"card_id": "CARD", "option": 5}],
        [{"card_id": "CARD", "option": True}],
        [{"card_id": "CARD", "option": "delete"}],
        [{"card_id": "CARD", "option": 0}, {"card_id": "CARD", "option": 0}],
    ],
)
def test_bad_decisions_are_422_and_change_nothing(client, deck, add_card, decisions):
    card = add_card(deck)
    _suggestions(client)
    review = _review(client, deck.id)
    if isinstance(decisions, list):
        decisions = [
            {**item, "card_id": card.id} if isinstance(item, dict) and item["card_id"] == "CARD"
            else item
            for item in decisions
        ]

    assert _decide(client, review["id"], decisions).status_code == 422

    assert LeechReview.query.one().status == "pending"


def test_a_completed_review_is_409(client, deck, add_card):
    card = add_card(deck)
    _suggestions(client)
    review = _review(client, deck.id)
    decisions = [{"card_id": card.id, "option": None}]
    _decide(client, review["id"], decisions)

    assert _decide(client, review["id"], decisions).status_code == 409


def test_someone_elses_review_is_404(client, db, me, make_user, make_deck):
    other = make_user(email="other@example.com")
    review = LeechReview(
        user_id=other.id, deck_id=make_deck(other).id, status="pending",
        recommendations=[{"card_id": 1, "options": [option()]}],
    )
    db.session.add(review)
    db.session.commit()

    resp = _decide(client, review.id, [{"card_id": 1, "option": None}])

    assert resp.status_code == 404
    assert db.session.get(LeechReview, review.id).status == "pending"


def test_a_card_deleted_during_the_review_is_skipped(client, db, deck, add_card):
    card = add_card(deck)
    card_id = card.id
    _suggestions(client)
    review = _review(client, deck.id)
    db.session.delete(card)
    db.session.commit()

    resp = _decide(client, review["id"], [{"card_id": card_id, "option": 0}])

    assert resp.status_code == 200
    assert Card.query.count() == 0
    assert LeechReview.query.one().decisions[0]["kind"] is None
