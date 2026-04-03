"""
tests/test_scoring.py — Tests for the verdict, anomaly, and review-first logic.

These are the most important tests in the repo: the verdict rules and anomaly
detection determine what users see and act on. A subtle bug here (e.g. a
high_risk session being labelled review_required) would erode trust in the tool.

Run with: pytest tests/test_scoring.py -v
"""

import pytest

from tracecode.analysis.scoring import (
    compute_anomalies,
    compute_outcome_score,
    compute_review_first,
    compute_verdict,
    compute_wandering_score,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def session(**kwargs) -> dict:
    """Build a minimal session dict. Only supply the fields your test cares about."""
    defaults = {
        "ended_at": 1000,
        "test_outcome": None,
        "tree_dirty": 0,
        "sensitive_files_touched": 0,
        "persistence_rate": None,
        "persistence_reliable": 0,
        "commits_during": None,
        "hot_files": 0,
        "diff_lines": None,
        "test_source": None,
    }
    return {**defaults, **kwargs}


def touch(file_path: str, touch_count: int = 1, persisted: int | None = 1) -> dict:
    """Build a minimal file_touch dict."""
    return {
        "id": 1,
        "file_path": file_path,
        "touch_count": touch_count,
        "first_touch_at": 0,
        "last_touch_at": 1,
        "persisted": persisted,
    }


def risky(command: str, tier: str = "risky") -> dict:
    return {"id": 1, "command": command, "tier": tier, "reason": "test", "flagged_at": 0}


# ---------------------------------------------------------------------------
# compute_verdict
# ---------------------------------------------------------------------------

class TestComputeVerdict:
    def test_blocked_on_any_catastrophic(self):
        assert compute_verdict(1, 0, []) == "blocked"

    def test_blocked_ignores_everything_else(self):
        # Even with zero anomalies, one catastrophic command = blocked
        assert compute_verdict(1, 10, []) == "blocked"

    def test_trusted_when_all_clear(self):
        assert compute_verdict(0, 0, []) == "trusted"

    def test_trusted_with_caution_only_anomalies(self):
        # Caution-level anomalies (e.g. "no tests") should not affect verdict
        anomalies = [{"id": "no_tests", "label": "Tests not checked",
                      "detail": "", "severity": "caution"}]
        assert compute_verdict(0, 0, anomalies) == "trusted"

    def test_trusted_with_caveats_on_one_major(self):
        anomalies = [{"id": "dirty_tree", "label": "Uncommitted changes",
                      "detail": "", "severity": "major"}]
        assert compute_verdict(0, 0, anomalies) == "trusted_with_caveats"

    def test_trusted_with_caveats_on_minor_only(self):
        anomalies = [{"id": "no_commits", "label": "No commits made",
                      "detail": "", "severity": "minor"}]
        assert compute_verdict(0, 0, anomalies) == "trusted_with_caveats"

    def test_review_required_on_risky_command_no_anomalies(self):
        assert compute_verdict(0, 1, []) == "review_required"

    def test_review_required_on_two_major_anomalies(self):
        anomalies = [
            {"id": "dirty_tree", "label": "", "detail": "", "severity": "major"},
            {"id": "tests_failed", "label": "", "detail": "", "severity": "major"},
        ]
        assert compute_verdict(0, 0, anomalies) == "review_required"

    def test_high_risk_on_risky_plus_major(self):
        anomalies = [{"id": "dirty_tree", "label": "", "detail": "", "severity": "major"}]
        assert compute_verdict(0, 1, anomalies) == "high_risk"

    def test_high_risk_on_three_major_anomalies_no_risky_command(self):
        anomalies = [
            {"id": "a", "label": "", "detail": "", "severity": "major"},
            {"id": "b", "label": "", "detail": "", "severity": "major"},
            {"id": "c", "label": "", "detail": "", "severity": "major"},
        ]
        assert compute_verdict(0, 0, anomalies) == "high_risk"

    def test_review_required_not_high_risk_on_risky_with_minor_only(self):
        # Risky command + only minor anomalies → review_required, not high_risk
        anomalies = [{"id": "no_commits", "label": "", "detail": "", "severity": "minor"}]
        assert compute_verdict(0, 1, anomalies) == "review_required"

    def test_catastrophic_beats_high_risk(self):
        # Catastrophic should win even when high_risk conditions also exist
        anomalies = [
            {"id": "a", "label": "", "detail": "", "severity": "major"},
            {"id": "b", "label": "", "detail": "", "severity": "major"},
            {"id": "c", "label": "", "detail": "", "severity": "major"},
        ]
        assert compute_verdict(1, 5, anomalies) == "blocked"


# ---------------------------------------------------------------------------
# compute_anomalies
# ---------------------------------------------------------------------------

class TestComputeAnomalies:
    def test_no_anomalies_on_clean_session(self):
        s = session(test_outcome="pass", tree_dirty=0, commits_during=1,
                    persistence_rate=0.9, persistence_reliable=1)
        result = compute_anomalies(s, [], [])
        ids = [a["id"] for a in result]
        assert "tests_failed" not in ids
        assert "dirty_tree" not in ids
        assert "low_survival" not in ids

    def test_tests_failed_is_major(self):
        s = session(test_outcome="fail", test_source="pytest")
        result = compute_anomalies(s, [], [])
        ids = [a["id"] for a in result]
        assert "tests_failed" in ids
        assert next(a for a in result if a["id"] == "tests_failed")["severity"] == "major"

    def test_dirty_tree_is_major(self):
        s = session(tree_dirty=1)
        result = compute_anomalies(s, [], [])
        ids = [a["id"] for a in result]
        assert "dirty_tree" in ids
        assert next(a for a in result if a["id"] == "dirty_tree")["severity"] == "major"

    def test_sensitive_files_is_major(self):
        s = session(sensitive_files_touched=1)
        result = compute_anomalies(s, [touch(".env", persisted=1)], [])
        ids = [a["id"] for a in result]
        assert "sensitive_files" in ids
        assert next(a for a in result if a["id"] == "sensitive_files")["severity"] == "major"

    def test_sensitive_files_detail_lists_paths(self):
        s = session(sensitive_files_touched=1)
        touches = [touch(".env", persisted=1), touch("secrets.json", persisted=1)]
        result = compute_anomalies(s, touches, [])
        sf = next(a for a in result if a["id"] == "sensitive_files")
        assert ".env" in sf["detail"]

    def test_low_survival_is_major(self):
        s = session(persistence_rate=0.3, persistence_reliable=1)
        result = compute_anomalies(s, [], [])
        ids = [a["id"] for a in result]
        assert "low_survival" in ids
        assert next(a for a in result if a["id"] == "low_survival")["severity"] == "major"

    def test_low_survival_not_triggered_at_threshold(self):
        # Threshold is < 0.5, so exactly 0.5 should not trigger
        s = session(persistence_rate=0.5, persistence_reliable=1)
        result = compute_anomalies(s, [], [])
        assert "low_survival" not in [a["id"] for a in result]

    def test_low_survival_suppressed_when_unreliable(self):
        s = session(persistence_rate=0.1, persistence_reliable=0)
        result = compute_anomalies(s, [], [])
        assert "low_survival" not in [a["id"] for a in result]

    def test_no_commits_is_minor(self):
        s = session(commits_during=0, ended_at=1000)
        result = compute_anomalies(s, [], [])
        ids = [a["id"] for a in result]
        assert "no_commits" in ids
        assert next(a for a in result if a["id"] == "no_commits")["severity"] == "minor"

    def test_no_commits_suppressed_when_commits_made(self):
        s = session(commits_during=2)
        result = compute_anomalies(s, [], [])
        assert "no_commits" not in [a["id"] for a in result]

    def test_no_commits_suppressed_when_data_unavailable(self):
        # commits_during=None means data not yet available
        s = session(commits_during=None)
        result = compute_anomalies(s, [], [])
        assert "no_commits" not in [a["id"] for a in result]

    def test_file_churn_is_minor(self):
        s = session(hot_files=2)
        touches = [
            touch("src/auth.py", touch_count=4, persisted=1),
            touch("src/db.py", touch_count=3, persisted=1),
        ]
        result = compute_anomalies(s, touches, [])
        ids = [a["id"] for a in result]
        assert "file_churn" in ids
        assert next(a for a in result if a["id"] == "file_churn")["severity"] == "minor"

    def test_large_diff_is_minor(self):
        s = session(diff_lines=600)
        result = compute_anomalies(s, [], [])
        ids = [a["id"] for a in result]
        assert "large_diff" in ids
        assert next(a for a in result if a["id"] == "large_diff")["severity"] == "minor"

    def test_large_diff_not_triggered_below_500(self):
        s = session(diff_lines=499)
        result = compute_anomalies(s, [], [])
        assert "large_diff" not in [a["id"] for a in result]

    def test_no_tests_is_caution(self):
        s = session(test_outcome=None, ended_at=1000)
        result = compute_anomalies(s, [], [])
        ids = [a["id"] for a in result]
        assert "no_tests" in ids
        assert next(a for a in result if a["id"] == "no_tests")["severity"] == "caution"

    def test_no_tests_suppressed_when_tests_ran(self):
        s = session(test_outcome="pass")
        result = compute_anomalies(s, [], [])
        assert "no_tests" not in [a["id"] for a in result]

    def test_majors_appear_before_minors(self):
        s = session(test_outcome="fail", tree_dirty=1, commits_during=0,
                    ended_at=1000, diff_lines=600)
        result = compute_anomalies(s, [], [])
        severities = [a["severity"] for a in result]
        saw_minor = False
        for sev in severities:
            if sev in ("minor", "caution"):
                saw_minor = True
            if saw_minor and sev == "major":
                pytest.fail(f"major anomaly appeared after minor: {severities}")

    def test_runtime_checkpoint_is_minor(self):
        s = session()
        events = [{"event_type": "blast_radius", "payload": "{}", "fired_at": 1}]
        result = compute_anomalies(s, [], [], session_events=events)
        ids = [a["id"] for a in result]
        assert "runtime_checkpoint" in ids
        cp = next(a for a in result if a["id"] == "runtime_checkpoint")
        assert cp["severity"] == "minor"
        assert "blast radius spike" in cp["detail"]


# ---------------------------------------------------------------------------
# compute_review_first
# ---------------------------------------------------------------------------

class TestComputeReviewFirst:
    def test_empty_when_no_touches(self):
        assert compute_review_first([], [], "trusted", None) == []

    def test_persisted_file_included(self):
        result = compute_review_first(
            [touch("src/auth.py", touch_count=1, persisted=1)],
            [], "review_required", None,
        )
        assert len(result) == 1
        assert result[0]["file_path"] == "src/auth.py"

    def test_unpersisted_low_touch_suppressed(self):
        # One touch, didn't persist → no meaningful signal → excluded
        result = compute_review_first(
            [touch("src/utils.py", touch_count=1, persisted=0)],
            [], "trusted", None,
        )
        assert result == []

    def test_sensitive_file_gets_config_sensitive_reason(self):
        result = compute_review_first(
            [touch(".env", touch_count=1, persisted=1)],
            [], "review_required", None,
        )
        assert "config-sensitive" in result[0]["reasons"]

    def test_unstable_edits_surfaces_non_persisted_hot_file(self):
        # 4 touches but nothing persisted → "unstable edits" signal
        result = compute_review_first(
            [touch("src/auth.py", touch_count=4, persisted=0)],
            [], "review_required", None,
        )
        assert len(result) == 1
        assert "unstable edits" in result[0]["reasons"]

    def test_high_priority_when_score_at_least_50(self):
        # persisted (30) + sensitive (25) = 55 → HIGH
        result = compute_review_first(
            [touch(".env", touch_count=1, persisted=1)],
            [], "review_required", None,
        )
        assert result[0]["priority"] == "HIGH"

    def test_medium_priority_when_score_below_50(self):
        # persisted only (30) → MEDIUM
        result = compute_review_first(
            [touch("src/auth.py", touch_count=1, persisted=1)],
            [], "review_required", None,
        )
        assert result[0]["priority"] == "MEDIUM"

    def test_suppressed_for_trusted_with_no_high_priority_files(self):
        result = compute_review_first(
            [touch("src/auth.py", touch_count=1, persisted=1)],
            [], "trusted", None,
        )
        assert result == []

    def test_not_suppressed_for_trusted_when_high_priority_file_exists(self):
        # Even a trusted session should show a sensitive file that was modified
        result = compute_review_first(
            [touch(".env", touch_count=1, persisted=1)],
            [], "trusted", 100,
        )
        assert len(result) == 1

    def test_flagged_command_adds_reason(self):
        result = compute_review_first(
            [touch("src/auth.py", touch_count=1, persisted=1)],
            [risky("sudo rm src/auth.py")],
            "review_required", None,
        )
        assert "in flagged command" in result[0]["reasons"]

    def test_sorted_by_score_descending(self):
        touches = [
            touch("src/low.py", touch_count=1, persisted=1),   # 30
            touch(".env", touch_count=1, persisted=1),           # 55
            touch("src/mid.py", touch_count=3, persisted=1),    # 50
        ]
        result = compute_review_first(touches, [], "review_required", 100)
        scores = [r["score"] for r in result]
        assert scores == sorted(scores, reverse=True)

    def test_max_files_respected(self):
        touches = [touch(f"src/file{i}.py", touch_count=1, persisted=1) for i in range(10)]
        result = compute_review_first(touches, [], "review_required", 100, max_files=3)
        assert len(result) <= 3

    def test_at_most_two_reasons_per_file(self):
        # File hits many signals — only top 2 reasons should be surfaced
        result = compute_review_first(
            [touch(".env", touch_count=4, persisted=1)],
            [risky("sudo rm .env")],
            "review_required", 100,
        )
        assert len(result[0]["reasons"]) <= 2


# ---------------------------------------------------------------------------
# compute_wandering_score
# ---------------------------------------------------------------------------

class TestComputeWanderingScore:
    def test_zero_when_no_files_touched(self):
        assert compute_wandering_score(0, 0) == 0.0

    def test_zero_when_no_hot_files(self):
        assert compute_wandering_score(10, 0) == 0.0

    def test_one_when_all_files_hot(self):
        assert compute_wandering_score(5, 5) == 1.0

    def test_proportional(self):
        assert compute_wandering_score(10, 5) == 0.5


# ---------------------------------------------------------------------------
# compute_outcome_score
# ---------------------------------------------------------------------------

class TestComputeOutcomeScore:
    def test_one_when_only_clean_tree(self):
        # tree_dirty=False (clean tree) always scores +1 — it's a positive signal.
        # No commits, no test data, no persistence → minimum score is 1, not 0.
        assert compute_outcome_score(0, False, None, None, False) == 1

    def test_zero_when_tree_dirty_and_nothing_else(self):
        # Dirty tree + no commits + no test data = truly nothing positive = 0
        assert compute_outcome_score(0, True, None, None, False) == 0

    def test_four_when_all_signals_positive(self):
        assert compute_outcome_score(1, False, "pass", 0.9, True) == 4

    def test_test_fail_does_not_add_point(self):
        # committed + clean tree + high persistence = 3 (no test point)
        assert compute_outcome_score(1, False, "fail", 0.9, True) == 3

    def test_persistence_ignored_when_unreliable(self):
        score_reliable   = compute_outcome_score(1, False, "pass", 0.9, True)
        score_unreliable = compute_outcome_score(1, False, "pass", 0.9, False)
        assert score_reliable == 4
        assert score_unreliable == 3
