"""The retrieval evaluation's own logic. Real results come from `evals.retrieval`."""

from evals.retrieval import duplicates_report, rank_of, scores, search_report, sweep
from evals.retrieval_cases import CARD_PAIRS, PASSAGES, SEARCH_CASES


def test_cases_are_consistent():
    names = [case["name"] for case in [*SEARCH_CASES, *CARD_PAIRS]]
    assert len(names) == len(set(names))
    assert all(case["expected"] in {None, *PASSAGES} for case in SEARCH_CASES)
    assert {pair["same"] for pair in CARD_PAIRS} == {True, False}


def test_rank_counts_from_one_and_a_miss_has_none():
    assert rank_of(["a", "b"], "b") == 2
    assert rank_of(["a", "b"], "c") is None


def test_scores_reward_a_high_rank():
    results = scores({"expected": "a"}, {"rank": 2})["results"]
    assert results == [
        {"key": "hit", "score": True},
        {"key": "reciprocal_rank", "score": 0.5},
    ]


def test_a_miss_scores_nothing():
    results = scores({"expected": "a"}, {"rank": None})["results"]
    assert [result["score"] for result in results] == [False, 0]


def test_off_topic_scores_whether_nothing_came_back():
    assert scores({"expected": None}, {"returned": 0})["results"][0]["score"] is True
    assert scores({"expected": None}, {"returned": 2})["results"][0]["score"] is False


def test_sweep_counts_each_side_of_the_threshold():
    assert sweep([0.9, 0.6], [0.7, 0.4], [0.5, 0.8]) == [(0.5, 2, 1), (0.8, 1, 2)]


def test_search_report_gives_metrics_and_names_each_case():
    report = search_report(
        [
            {"name": "good", "expected": "a", "closest": 0.8, "returned": 5, "rank": 2},
            {"name": "away", "expected": None, "closest": 0.3, "returned": 0, "rank": None},
        ]
    )
    assert "hit rate at 5 1/1, MRR 0.50, off topic refused 1/1" in report
    assert "0.800  good (rank 2)" in report
    assert "0.300  away (off topic)" in report


def test_duplicates_report_says_which_pairs_are_the_same_fact():
    report = duplicates_report(
        [
            {"name": "twin", "same": True, "similarity": 0.98},
            {"name": "false", "same": False, "similarity": 0.96},
        ]
    )
    assert "0.980  twin (same fact)" in report
    assert "0.960  false (different)" in report
