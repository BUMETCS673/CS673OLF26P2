"""The deck tutor's graph and routes, with checkpoints kept in memory."""

import uuid
from contextlib import asynccontextmanager
from dataclasses import replace

import pytest
from ai_fakes import ScriptedChatModel, ScriptedModel
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import delete, func, select

from app.ai.checkpoints import discard_threads, open_checkpointer
from app.ai.judge import PASSED
from app.ai.models import AIUnavailable, Role
from app.ai.schemas import CardDraft, Verdict, Verdicts
from app.ai.tutor.context import TutorContext
from app.ai.tutor.graph import (
    CANT_ANSWER,
    CANT_VERIFY,
    TurnOutcome,
    read_messages,
    resume_turn,
    run_turn,
)
from app.core.settings import EMBEDDING_DIMENSIONS, get_settings
from app.models import Card, Deck, Job, TutorConversation
from app.models.job import EMBED_CARDS
from app.models.tutor import AWAITING_DECISION, IDLE, REPLYING
from app.repositories.cards import CardRepository
from app.services import tutor as service_module

CARD = {"front": "What is the capital of Peru?", "back": "Lima", "lapses": 2}
NEW_CARD = {"front": "What is the capital of Chile?", "back": "Santiago"}


def _call(name: str, **args) -> AIMessage:
    call = {"name": name, "args": args, "id": f"call-{name}", "type": "tool_call"}
    return AIMessage("", tool_calls=[call])


def _proposal() -> AIMessage:
    return _call("propose_cards", cards=[NEW_CARD])


def _verdicts(ok: bool) -> Verdicts:
    return Verdicts(verdicts=[Verdict(index=0, ok=ok)])


class FailingChatModel(BaseChatModel):
    @property
    def _llm_type(self) -> str:
        return "failing"

    def bind_tools(self, tools, **_):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **_):
        raise AIUnavailable()


class RecordingChatModel(ScriptedChatModel):
    """Also keeps the messages of each call."""

    seen: list = []

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.seen.append(messages)
        return super()._generate(messages, stop, run_manager, **kwargs)


def _context(writer, judge=None) -> TutorContext:
    return TutorContext(
        writer=writer, judge=judge or ScriptedModel(), deck_name="Capitals", cards=[CARD]
    )


# --- the graph ----------------------------------------------------------------------------


async def test_a_reply_ends_the_turn():
    model = ScriptedChatModel(replies=[AIMessage("Think of the Andes.")])
    outcome = await run_turn(_context(model), InMemorySaver(), "t", "Hi")
    assert outcome.proposal is None
    assert [item["text"] for item in outcome.messages] == ["Hi", "Think of the Andes."]


async def test_tool_results_reach_the_model_but_not_the_learner():
    model = RecordingChatModel(
        replies=[_call("search_deck", query="capital Peru"), AIMessage("Try it.")]
    )
    outcome = await run_turn(_context(model), InMemorySaver(), "t", "Quiz me")
    assert "Lima" in model.seen[1][-1].content
    assert [item["text"] for item in outcome.messages] == ["Quiz me", "Try it."]


async def test_the_judge_sees_the_cards_found_near_the_proposal():
    judge = ScriptedModel(_verdicts(True))
    searched = []

    async def find_existing(drafts):
        searched.append([draft.front for draft in drafts])
        return [CardDraft(front="Capital of Bolivia?", back="Sucre")]

    writer = ScriptedChatModel(replies=[_proposal()])
    context = replace(_context(writer, judge), find_existing=find_existing)

    await run_turn(context, InMemorySaver(), "t", "Add a card")

    assert searched == [[NEW_CARD["front"]]]
    assert "Capital of Bolivia?" in judge.prompts[0][-1].content


async def test_search_finds_cards_by_meaning_and_by_words():
    meaning = {"front": "Main city of Bolivia?", "back": "Sucre", "lapses": 0}

    async def find_similar(_query):
        return [meaning]

    model = RecordingChatModel(
        replies=[_call("search_deck", query="capital"), AIMessage("Try it.")]
    )
    context = replace(_context(model), find_similar=find_similar)
    await run_turn(context, InMemorySaver(), "t", "Quiz me")
    result = model.seen[1][-1].content
    assert "Sucre" in result  # shares no words with the query
    assert "Lima" in result  # shares a word, even with no vector


async def test_the_nearest_cards_are_from_this_deck_and_model(
    session, make_user, make_deck, make_card
):
    user = await make_user("near@example.com")
    deck, other_deck = await make_deck(user), await make_deck(user, name="Other")
    near = [1.0, *[0.0] * (EMBEDDING_DIMENSIONS - 1)]
    far = [0.0, 1.0, *[0.0] * (EMBEDDING_DIMENSIONS - 2)]

    await make_card(deck, front="Far?", embedding=far, embedding_model="m")
    await make_card(deck, front="Near?", embedding=near, embedding_model="m")
    await make_card(deck, front="No vector?")
    await make_card(deck, front="Old model?", embedding=near, embedding_model="old")
    await make_card(other_deck, front="Other deck?", embedding=near, embedding_model="m")

    found = await CardRepository(session).nearest_in_deck(deck.id, near, "m", 10)
    assert [card.front for card in found] == ["Near?", "Far?"]


async def test_the_last_call_has_no_tools():
    model = ScriptedChatModel(
        replies=[_call("weak_cards"), _call("weak_cards"), AIMessage("Here goes.")]
    )
    outcome = await run_turn(_context(model), InMemorySaver(), "t", "Quiz me")
    assert len(model.offered) == 2  # the third call never bound any tools
    assert outcome.messages[-1]["text"] == "Here goes."


async def test_an_empty_reply_says_it_could_not_answer():
    model = ScriptedChatModel(replies=[AIMessage("")])
    outcome = await run_turn(_context(model), InMemorySaver(), "t", "Hi")
    assert outcome.messages[-1]["text"] == CANT_ANSWER


async def test_a_model_failure_shows_a_notice_the_model_never_sees():
    saver = InMemorySaver()
    outcome = await run_turn(_context(FailingChatModel()), saver, "t", "Hi")
    assert outcome.messages[-1]["error"] is True

    model = RecordingChatModel(replies=[AIMessage("Hello.")])
    await run_turn(_context(model), saver, "t", "Again")
    assert all(outcome.messages[-1]["text"] not in str(m.content) for m in model.seen[0])


async def test_a_history_window_never_starts_on_a_tool_result():
    saver = InMemorySaver()
    for turn in range(6):
        model = RecordingChatModel(replies=[_call("weak_cards"), AIMessage(f"Reply {turn}")])
        await run_turn(_context(model), saver, "t", f"Message {turn}")
    without_system = [m for m in model.seen[0] if m.type != "system"]
    assert len(without_system) <= 12
    assert without_system[0].type == "human"


async def test_proposed_cards_pause_until_resumed():
    saver = InMemorySaver()
    writer = ScriptedChatModel(replies=[_proposal()])
    context = _context(writer, ScriptedModel(_verdicts(True)))
    outcome = await run_turn(context, saver, "t", "Make a card")
    assert outcome.proposal["cards"] == [NEW_CARD]

    await resume_turn(saver, "t", "Added 1 card to your deck.")
    messages = await read_messages(saver, "t")
    assert messages[-1]["text"] == "Added 1 card to your deck."


async def test_a_rejected_card_is_not_proposed():
    writer = ScriptedChatModel(replies=[_proposal()])
    context = _context(writer, ScriptedModel(_verdicts(False)))
    outcome = await run_turn(context, InMemorySaver(), "t", "Make a card")
    assert outcome.proposal is None
    assert outcome.messages[-1]["text"] == CANT_VERIFY


async def test_a_chat_is_saved_and_resumed_in_postgres(engine):
    url = engine.url.render_as_string(hide_password=False)
    thread_id = str(uuid.uuid4())
    writer = ScriptedChatModel(replies=[_proposal()])
    context = _context(writer, ScriptedModel(_verdicts(True)))
    try:
        async with open_checkpointer(url) as saver:
            outcome = await run_turn(context, saver, thread_id, "Make a card")
        assert outcome.proposal["cards"] == [NEW_CARD]

        # A new checkpointer, as a later request would have.
        async with open_checkpointer(url) as saver:
            await resume_turn(saver, thread_id, "Added 1 card to your deck.")
            messages = await read_messages(saver, thread_id)
        assert [item["text"] for item in messages] == ["Make a card", "Added 1 card to your deck."]
    finally:
        await discard_threads(url, [thread_id])


# --- the routes ---------------------------------------------------------------------------


@pytest.fixture
async def deck(make_deck, me):
    return await make_deck(me)


@pytest.fixture
def models(monkeypatch):
    """Sets what the next turn's models answer, and keeps checkpoints in memory."""
    saver = InMemorySaver()

    @asynccontextmanager
    async def memory(_url):
        yield saver

    async def no_discard(_url, _threads):
        return None

    monkeypatch.setattr(service_module, "open_checkpointer", memory)
    monkeypatch.setattr(service_module, "discard_threads", no_discard)

    def _set(*replies, verdicts=None):
        chosen = {
            Role.HELPER: ScriptedChatModel(replies=list(replies)),
            Role.JUDGE: ScriptedModel(*([verdicts] if verdicts else [])),
        }
        monkeypatch.setattr(service_module, "load_chat_model", lambda role, *_, **__: chosen[role])

    return _set


async def _propose(client, deck, models) -> dict:
    models(_proposal(), verdicts=_verdicts(True))
    response = await client.post(
        f"/api/decks/{deck.id}/tutor/messages", json={"text": "Make a card"}
    )
    assert response.status_code == 200
    return response.json()


async def test_a_new_deck_has_an_empty_chat(client, deck):
    response = await client.get(f"/api/decks/{deck.id}/tutor")
    assert response.status_code == 200
    assert response.json() == {
        "enabled": True, "status": IDLE, "messages": [], "proposal": None,
    }


async def test_someone_elses_deck_is_not_found(client, make_user, make_deck, me):
    other = await make_deck(await make_user("other@example.com"))
    assert (await client.get(f"/api/decks/{other.id}/tutor")).status_code == 404
    response = await client.post(f"/api/decks/{other.id}/tutor/messages", json={"text": "Hi"})
    assert response.status_code == 404


async def test_a_message_returns_the_reply_and_reading_finds_it(client, deck, models):
    models(AIMessage("Hello."))
    response = await client.post(f"/api/decks/{deck.id}/tutor/messages", json={"text": "Hi"})
    assert response.status_code == 200
    assert response.json()["status"] == IDLE
    assert response.json()["messages"][-1] == {"role": "tutor", "text": "Hello.", "error": False}

    stored = await client.get(f"/api/decks/{deck.id}/tutor")
    assert stored.json()["messages"] == response.json()["messages"]


async def test_an_empty_message_is_rejected(client, deck, models):
    response = await client.post(f"/api/decks/{deck.id}/tutor/messages", json={"text": "  "})
    assert response.status_code in (400, 422)


async def test_turning_it_off_stops_messages(client, deck, models, monkeypatch):
    monkeypatch.setattr(get_settings(), "ai_tutor_enabled", False)
    response = await client.post(f"/api/decks/{deck.id}/tutor/messages", json={"text": "Hi"})
    assert response.status_code == 503


async def test_the_learners_budget_stops_messages(client, deck, models, monkeypatch):
    monkeypatch.setattr(get_settings(), "ai_tutor_user_daily_limit", 0)
    response = await client.post(f"/api/decks/{deck.id}/tutor/messages", json={"text": "Hi"})
    assert response.status_code == 429


async def test_a_reply_in_progress_blocks_another_message(client, session, deck, models):
    models(AIMessage("Hello."))
    await client.post(f"/api/decks/{deck.id}/tutor/messages", json={"text": "Hi"})
    conversation = await session.scalar(select(TutorConversation))
    conversation.status = REPLYING
    await session.commit()

    response = await client.post(f"/api/decks/{deck.id}/tutor/messages", json={"text": "Hi"})
    assert response.status_code == 409


async def test_accepting_adds_the_servers_cards_and_queues_embedding(
    client, session, deck, models
):
    view = await _propose(client, deck, models)
    assert view["status"] == AWAITING_DECISION

    blocked = await client.post(f"/api/decks/{deck.id}/tutor/messages", json={"text": "Hi"})
    assert blocked.status_code == 409

    url = f"/api/decks/{deck.id}/tutor/proposal"
    body = {"proposal_id": view["proposal"]["id"], "accept": True}
    response = await client.post(url, json=body)
    assert response.status_code == 200
    assert response.json()["status"] == IDLE
    assert response.json()["messages"][-1]["text"] == "Added 1 card to your deck."

    card = await session.scalar(select(Card).where(Card.deck_id == deck.id))
    assert (card.front, card.back, card.origin) == (NEW_CARD["front"], NEW_CARD["back"], "ai")
    job = await session.scalar(select(Job).where(Job.kind == EMBED_CARDS))
    assert job.payload == {"card_ids": [card.id]}

    # A proposal can only be used once.
    assert (await client.post(url, json=body)).status_code == 409


async def test_declining_adds_nothing(client, session, deck, models):
    view = await _propose(client, deck, models)
    response = await client.post(
        f"/api/decks/{deck.id}/tutor/proposal",
        json={"proposal_id": view["proposal"]["id"], "accept": False},
    )
    assert response.status_code == 200
    assert await session.scalar(select(func.count()).select_from(Card)) == 0


async def test_a_wrong_proposal_id_is_refused(client, deck, models):
    await _propose(client, deck, models)
    response = await client.post(
        f"/api/decks/{deck.id}/tutor/proposal", json={"proposal_id": "wrong", "accept": True}
    )
    assert response.status_code == 409


async def test_deleting_the_deck_during_a_reply_is_not_found(
    client, session, deck, models, monkeypatch
):
    models()
    deck_id = deck.id

    async def delete_during_turn(*_):
        await session.execute(delete(Deck).where(Deck.id == deck_id))
        await session.commit()
        return TurnOutcome([], None, PASSED)

    monkeypatch.setattr(service_module, "run_turn", delete_during_turn)
    response = await client.post(f"/api/decks/{deck_id}/tutor/messages", json={"text": "Hi"})
    assert response.status_code == 404


async def test_reset_deletes_the_chat(client, session, deck, models):
    models(AIMessage("Hello."))
    await client.post(f"/api/decks/{deck.id}/tutor/messages", json={"text": "Hi"})
    reset = await client.delete(f"/api/decks/{deck.id}/tutor")

    assert reset.status_code == 204
    assert await session.scalar(select(func.count()).select_from(TutorConversation)) == 0
