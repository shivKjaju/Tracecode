"""
tests/test_scoring.py — Tests for analysis/scoring.py

Pure function tests: no I/O, no DB, no filesystem.
"""

import pytest

from tracecode.analysis.scoring import (
    classify_outcome,
    compute_all,
    compute_outcome_score,
    compute_quality_score,
    compute_wandering_score,
)


# ---------------------------------------------------------------------------
# compute_wandering_score
# ---------------------------------------------------------------------------

class TestWanderingScore:
    def test_zero_when_no_files_touched(self) -> None:
        assert compute_wandering_score(0, 0) == 0.0

    def test_zero_when_no_hot_files(self) -> None:
        # 5 files touched, none hot
        assert compute_wandering_score(5, 0) == 0.0

    def test_one_when_all_hot(self) -> None:
        # Every touched file was hot
        assert compute_wandering_score(4, 4) == 1.0

    def test_partial_wandering(self) -> None:
        # 2 of 4 files were hot → 0.5
        assert compute_wandering_score(4, 2) == 0.5

    def test_capped_at_one(self) -> None:
        # hot_files > files_touched shouldn't produce > 1.0
        assert compute_wandering_score(2, 5) == 1.0

    def test_single_hot_file(self) -> None:
        assert compute_wandering_score(1, 1) == 1.0

    def test_single_non_hot_file(self) -> None:
        assert compute_wandering_score(1, 0) == 0.0

    def test_result_rounded_to_3_decimals(self) -> None:
        # 1/3 = 0.333...
        result = compute_wandering_score(3, 1)
        assert result == pytest.approx(0.333, abs=0.001)


# ---------------------------------------------------------------------------
# compute_outcome_score
# ---------------------------------------------------------------------------

class TestOutcomeScore:
    def test_zero_when_all_signals_bad(self) -> None:
        score = compute_outcome_score(
            commits_during=0,
            tree_dirty=True,
            test_outcome=None,
            persistence_rate=None,
            persistence_reliable=False,
        )
        assert score == 0

    def test_max_four_when_all_signals_good(self) -> None:
        score = compute_outcome_score(
            commits_during=1,
            tree_dirty=False,
            test_outcome="pass",
            persistence_rate=0.9,
            persistence_reliable=True,
        )
        assert score == 4

    def test_commit_adds_one(self) -> None:
        base = compute_outcome_score(0, True, None, None, False)
        with_commit = compute_outcome_score(1, True, None, None, False)
        assert with_commit == base + 1

    def test_clean_tree_adds_one(self) -> None:
        dirty = compute_outcome_score(0, True, None, None, False)
        clean = compute_outcome_score(0, False, None, None, False)
        assert clean == dirty + 1

    def test_test_pass_adds_one(self) -> None:
        no_test = compute_outcome_score(0, True, None, None, False)
        with_pass = compute_outcome_score(0, True, "pass", None, False)
        assert with_pass == no_test + 1

    def test_test_fail_adds_nothing(self) -> None:
        no_test = compute_outcome_score(0, True, None, None, False)
        with_fail = compute_outcome_score(0, True, "fail", None, False)
        assert with_fail == no_test

    def test_high_persistence_adds_one(self) -> None:
        no_persist = compute_outcome_score(0, True, None, None, False)
        with_persist = compute_outcome_score(0, True, None, 0.8, True)
        assert with_persist == no_persist + 1

    def test_low_persistence_adds_nothing(self) -> None:
        no_persist = compute_outcome_score(0, True, None, None, False)
        with_low = compute_outcome_score(0, True, None, 0.5, True)
        assert with_low == no_persist

    def test_persistence_threshold_is_70_percent(self) -> None:
        below = compute_outcome_score(0, True, None, 0.699, True)
        at    = compute_outcome_score(0, True, None, 0.700, True)
        assert below == 0
        assert at == 1

    def test_unreliable_persistence_not_counted(self) -> None:
        reliable = compute_outcome_score(0, True, None, 0.9, True)
        unreliable = compute_outcome_score(0, True, None, 0.9, False)
        assert reliable == 1
        assert unreliable == 0

    def test_none_persistence_rate_not_counted(self) -> None:
        score = compute_outcome_score(0, True, None, None, True)
        assert score == 0


# ---------------------------------------------------------------------------
# compute_quality_score
# ---------------------------------------------------------------------------

class TestQualityScore:
    def test_zero_for_worst_session(self) -> None:
        # outcome=0, wandering=1.0, no persistence
        score = compute_quality_score(0, 1.0, None, False)
        assert score == 0.0

    def test_one_for_best_session_without_persistence(self) -> None:
        # outcome=4/4=1.0, wandering=0 → quality=0.60+0.40=1.0
        score = compute_quality_score(4, 0.0, None, False)
        assert score == pytest.approx(1.0)

    def test_one_for_best_session_with_persistence(self) -> None:
        # outcome=4/4=1.0, wandering=0, persistence=1.0 → 0.55+0.25+0.20=1.0
        score = compute_quality_score(4, 0.0, 1.0, True)
        assert score == pytest.approx(1.0)

    def test_uses_two_signal_formula_when_persistence_unreliable(self) -> None:
        s1 = compute_quality_score(2, 0.5, 0.9, False)   # unreliable
        s2 = compute_quality_score(2, 0.5, None, False)   # no data
        # Both should use the 60/40 formula and give same result
        assert s1 == pytest.approx(s2)

    def test_uses_three_signal_formula_when_persistence_reliable(self) -> None:
        two_signal   = compute_quality_score(2, 0.0, None, False)
        three_signal = compute_quality_score(2, 0.0, 1.0, True)
        # Three-signal includes persistence bonus → higher score
        assert three_signal > two_signal

    def test_result_between_zero_and_one(self) -> None:
        for outcome in range(5):
            for wandering in [0.0, 0.5, 1.0]:
                score = compute_quality_score(outcome, wandering, None, False)
                assert 0.0 <= score <= 1.0, f"Out of range: {score}"

    def test_higher_outcome_gives_higher_quality(self) -> None:
        low  = compute_quality_score(1, 0.5, None, False)
        high = compute_quality_score(3, 0.5, None, False)
        assert high > low

    def test_lower_wandering_gives_higher_quality(self) -> None:
        high_wander = compute_quality_score(2, 0.8, None, False)
        low_wander  = compute_quality_score(2, 0.2, None, False)
        assert low_wander > high_wander

    def test_rounded_to_3_decimal_places(self) -> None:
        score = compute_quality_score(1, 0.333, None, False)
        assert score == round(score, 3)


# ---------------------------------------------------------------------------
# classify_outcome
# ---------------------------------------------------------------------------

class TestClassifyOutcome:
    def test_zero_is_incomplete(self) -> None:
        assert classify_outcome(0) == "incomplete"

    def test_one_is_partial(self) -> None:
        assert classify_outcome(1) == "partial"

    def test_two_is_partial(self) -> None:
        assert classify_outcome(2) == "partial"

    def test_three_is_success(self) -> None:
        assert classify_outcome(3) == "success"

    def test_four_is_success(self) -> None:
        assert classify_outcome(4) == "success"


# ---------------------------------------------------------------------------
# compute_all
# ---------------------------------------------------------------------------

class TestComputeAll:
    def make_session(self, **overrides) -> dict:
        base = {
            "files_touched":      4,
            "hot_files":          1,
            "commits_during":     1,
            "tree_dirty":         0,
            "test_outcome":       "pass",
            "persistence_rate":   0.8,
            "persistence_reliable": 1,
        }
        base.update(overrides)
        return base

    def test_returns_all_four_keys(self) -> None:
        result = compute_all(self.make_session())
        assert set(result.keys()) == {
            "wandering_score", "outcome_score", "quality_score", "auto_outcome"
        }

    def test_good_session_scores_high(self) -> None:
        result = compute_all(self.make_session())
        assert result["outcome_score"] == 4
        assert result["quality_score"] > 0.8
        assert result["auto_outcome"] == "success"

    def test_bad_session_scores_low(self) -> None:
        result = compute_all(self.make_session(
            files_touched=6,
            hot_files=4,
            commits_during=0,
            tree_dirty=1,
            test_outcome="fail",
            persistence_rate=0.2,
            persistence_reliable=1,
        ))
        assert result["outcome_score"] == 0
        assert result["quality_score"] < 0.5
        assert result["auto_outcome"] == "incomplete"

    def test_handles_none_values(self) -> None:
        # Session with no data (e.g. git analysis failed).
        # tree_dirty defaults to False (bool(None)==False) → clean tree = +1 point.
        result = compute_all({})
        assert result["wandering_score"] == 0.0
        assert result["outcome_score"] == 1     # clean tree scores +1
        assert result["auto_outcome"] == "partial"
        assert 0.0 <= result["quality_score"] <= 1.0

    def test_handles_integer_booleans_from_sqlite(self) -> None:
        # SQLite stores booleans as 0/1 integers
        result = compute_all(self.make_session(tree_dirty=0, persistence_reliable=1))
        assert result["outcome_score"] >= 1   # clean tree counted

    def test_wandering_score_present(self) -> None:
        result = compute_all(self.make_session(files_touched=4, hot_files=2))
        assert result["wandering_score"] == pytest.approx(0.5)
