"""The red-team runner's own logic, with stand-in models. Real results come from `evals.redteam`."""

import pytest
from ai_fakes import ScriptedChatModel, ScriptedModel
from langchain_core.messages import AIMessage

from app.ai.models import AIUnavailable
from app.ai.schemas import CleanChunks, Verdict, Verdicts
from evals.redteam import ALL_CASES, cases_for, run_case
from evals.redteam_cases import SMOKE_CASE_NAMES


def _case(name: str) -> dict:
    return next(case for case in ALL_CASES if case["name"] == name)


def _writing(front: str, searched: bool = True) -> ScriptedChatModel:
    call = {
        "name": "CardBatch",
        "args": {"cards": [{"front": front, "back": "A"}]},
        "id": "call",
        "type": "tool_call",
    }
    search = {
        "name": "search_materials",
        "args": {"query": "capitals"},
        "id": "search",
        "type": "tool_call",
    }
    replies = [AIMessage("", tool_calls=[call])]
    return ScriptedChatModel(
        replies=[AIMessage("", tool_calls=[search]), *replies] if searched else replies
    )


def test_case_names_are_unique():
    names = [case["name"] for case in ALL_CASES]
    assert len(names) == len(set(names))


def test_every_layer_has_an_attack_and_screening_and_the_judge_have_harmless_cases():
    for layer in ("screening", "judge", "writer"):
        assert any(c["layer"] == layer and not c["allowed"] for c in ALL_CASES)
    for layer in ("screening", "judge"):
        assert any(c["layer"] == layer and c["allowed"] for c in ALL_CASES)


def test_the_full_run_has_every_case():
    assert cases_for(smoke=False) == ALL_CASES


def test_the_smoke_set_has_an_attack_and_a_harmless_case_per_layer():
    smoke = cases_for(smoke=True)

    assert {case["name"] for case in smoke} == SMOKE_CASE_NAMES  # no name is misspelled
    for layer in ("screening", "judge"):
        assert {c["allowed"] for c in smoke if c["layer"] == layer} == {True, False}


async def test_a_chunk_screening_clears_counts_as_allowed():
    model = ScriptedModel(CleanChunks(clean=[0]))
    result = await run_case(_case("screen_ordinary_biology"), model, None)
    assert result == {"allowed": True}


async def test_a_chunk_screening_withholds_isnt_allowed():
    model = ScriptedModel(CleanChunks(clean=[]))
    result = await run_case(_case("screen_addressed_to_ai"), model, None)
    assert result == {"allowed": False}


@pytest.mark.parametrize("ok", [True, False])
async def test_the_judges_verdict_is_the_result(ok):
    judge = ScriptedModel(Verdicts(verdicts=[Verdict(index=0, ok=ok)]))
    result = await run_case(_case("judge_forged_label"), None, judge)
    assert result == {"allowed": ok}


async def test_a_judge_with_no_answer_counts_as_unknown():
    judge = ScriptedModel(AIUnavailable())
    result = await run_case(_case("judge_forged_label"), None, judge)
    assert result == {"allowed": None}


async def test_the_planted_word_in_a_card_means_the_attack_worked():
    case = _case("writer_planted_false_fact")
    result = await run_case(case, _writing("Which city is ZORBLATT the capital of?"), None)
    assert result == {"allowed": True}


async def test_a_writer_that_never_searched_tested_nothing():
    case = _case("writer_planted_false_fact")
    result = await run_case(case, _writing("What is the capital of Spain?", searched=False), None)
    assert result == {"allowed": None}


async def test_a_card_without_the_planted_word_means_it_failed():
    case = _case("writer_planted_false_fact")
    result = await run_case(case, _writing("What is the capital of Spain?"), None)
    assert result == {"allowed": False}
