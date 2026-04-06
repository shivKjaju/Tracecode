"""
tests/test_summary.py — Tests for tracecode/output/summary.py

Tests cover:
  1. Trusted session → single header line only
  2. Trusted with caveats → shows minor anomaly reason (preference #1)
  3. Trusted with caveats + review file → shows top file even if MEDIUM priority
  4. Review required → shows major anomalies and HIGH review files
  5. High risk → shows risky commands and anomalies
  6. Blocked → shows catastrophic command count
  7. Compact mode → single line
  8. Full mode → all anomalies + up to 5 review files
  9. Protected path reason → surfaces in review section
  10. Edge cases: no anomalies, no review files, missing session fields
"""

from tracecode.output.summary import render_session_summary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def session(**kwargs) -> dict:
    """Build a minimal session dict with sensible defaults."""
    base = {
        "id": "8a3f1b2c-dead-beef-1234-567890abcdef",
        "project_name": "myproject",
        "started_at": 1000000,
        "ended_at": 1000150,   # 2m 30s
        "verdict": "trusted",
    }
    base.update(kwargs)
    return base


def risk_counts(risky: int = 0, catastrophic: int = 0) -> dict:
    return {"risky": risky, "catastrophic": catastrophic}


def anomaly(id_: str, label: str, severity: str, detail: str = "") -> dict:
    return {"id": id_, "label": label, "detail": detail, "severity": severity}


def review_file(path: str, score: int, reasons: list[str], priority: str = "HIGH") -> dict:
    return {"file_path": path, "score": score, "reasons": reasons, "priority": priority}


# ---------------------------------------------------------------------------
# 1. Trusted session
# ---------------------------------------------------------------------------

class TestTrustedSession:
    def test_single_line_output(self) -> None:
        result = render_session_summary(
            session=session(verdict="trusted"),
            anomalies=[],
            review_first=[],
            risk_counts=risk_counts(),
            use_color=False,
        )
        lines = [l for l in result.splitlines() if l.strip()]
        assert len(lines) == 1

    def test_contains_trusted_label(self) -> None:
        result = render_session_summary(
            session=session(verdict="trusted"),
            anomalies=[],
            review_first=[],
            risk_counts=risk_counts(),
            use_color=False,
        )
        assert "Trusted" in result

    def test_no_review_section(self) -> None:
        result = render_session_summary(
            session=session(verdict="trusted"),
            anomalies=[],
            review_first=[review_file("src/main.py", 40, ["repeated edits"], "MEDIUM")],
            risk_counts=risk_counts(),
            use_color=False,
        )
        assert "review" not in result.lower()

    def test_contains_session_id(self) -> None:
        result = render_session_summary(
            session=session(verdict="trusted"),
            anomalies=[],
            review_first=[],
            risk_counts=risk_counts(),
            use_color=False,
        )
        assert "8a3f1b2c"[:8] in result

    def test_contains_project_name(self) -> None:
        result = render_session_summary(
            session=session(verdict="trusted"),
            anomalies=[],
            review_first=[],
            risk_counts=risk_counts(),
            use_color=False,
        )
        assert "myproject" in result

    def test_contains_duration(self) -> None:
        result = render_session_summary(
            session=session(verdict="trusted"),
            anomalies=[],
            review_first=[],
            risk_counts=risk_counts(),
            use_color=False,
        )
        assert "2m" in result


# ---------------------------------------------------------------------------
# 2. Trusted with caveats — minor anomaly shown (preference #1)
# ---------------------------------------------------------------------------

class TestTrustedWithCaveats:
    def test_shows_verdict_label(self) -> None:
        result = render_session_summary(
            session=session(verdict="trusted_with_caveats"),
            anomalies=[anomaly("no_commits", "No commits made", "minor")],
            review_first=[],
            risk_counts=risk_counts(),
            use_color=False,
        )
        assert "Trusted with caveats" in result

    def test_shows_minor_anomaly_when_no_major(self) -> None:
        # Preference #1: minor anomaly shown so the summary is not empty
        result = render_session_summary(
            session=session(verdict="trusted_with_caveats"),
            anomalies=[anomaly("no_commits", "No commits made", "minor")],
            review_first=[],
            risk_counts=risk_counts(),
            use_color=False,
        )
        assert "no commits made" in result.lower()

    def test_shows_major_anomaly_over_minor(self) -> None:
        result = render_session_summary(
            session=session(verdict="trusted_with_caveats"),
            anomalies=[
                anomaly("dirty_tree", "Uncommitted changes at end", "major"),
                anomaly("no_commits", "No commits made", "minor"),
            ],
            review_first=[],
            risk_counts=risk_counts(),
            use_color=False,
        )
        assert "uncommitted changes at end" in result.lower()

    def test_shows_medium_review_file_when_no_high(self) -> None:
        # Preference #1: for caveat sessions show MEDIUM file so it's not empty
        result = render_session_summary(
            session=session(verdict="trusted_with_caveats"),
            anomalies=[anomaly("no_commits", "No commits made", "minor")],
            review_first=[review_file("src/auth.py", 30, ["repeated edits"], "MEDIUM")],
            risk_counts=risk_counts(),
            use_color=False,
        )
        assert "src/auth.py" in result

    def test_shows_review_reasons(self) -> None:
        result = render_session_summary(
            session=session(verdict="trusted_with_caveats"),
            anomalies=[anomaly("no_commits", "No commits made", "minor")],
            review_first=[review_file("src/auth.py", 55, ["protected path", "repeated edits"])],
            risk_counts=risk_counts(),
            use_color=False,
        )
        assert "protected path" in result
        assert "repeated edits" in result

    def test_includes_footer(self) -> None:
        result = render_session_summary(
            session=session(verdict="trusted_with_caveats"),
            anomalies=[anomaly("no_commits", "No commits made", "minor")],
            review_first=[],
            risk_counts=risk_counts(),
            use_color=False,
        )
        assert "tracecode review" in result


# ---------------------------------------------------------------------------
# 3. Review required
# ---------------------------------------------------------------------------

class TestReviewRequired:
    def test_shows_needs_review_label(self) -> None:
        result = render_session_summary(
            session=session(verdict="review_required"),
            anomalies=[anomaly("dirty_tree", "Uncommitted changes at end", "major")],
            review_first=[],
            risk_counts=risk_counts(),
            use_color=False,
        )
        assert "Needs Review" in result

    def test_shows_risky_command_count(self) -> None:
        result = render_session_summary(
            session=session(verdict="review_required"),
            anomalies=[],
            review_first=[],
            risk_counts=risk_counts(risky=2),
            use_color=False,
        )
        assert "2 risky commands" in result

    def test_shows_single_risky_command_no_plural(self) -> None:
        result = render_session_summary(
            session=session(verdict="review_required"),
            anomalies=[],
            review_first=[],
            risk_counts=risk_counts(risky=1),
            use_color=False,
        )
        assert "1 risky command" in result
        assert "commands" not in result

    def test_shows_high_priority_review_file(self) -> None:
        result = render_session_summary(
            session=session(verdict="review_required"),
            anomalies=[],
            review_first=[
                review_file("auth/middleware.py", 70, ["protected path", "repeated edits"]),
            ],
            risk_counts=risk_counts(),
            use_color=False,
        )
        assert "auth/middleware.py" in result

    def test_suppresses_medium_priority_file(self) -> None:
        # In summary mode, MEDIUM priority files are not shown (not enough signal)
        result = render_session_summary(
            session=session(verdict="review_required"),
            anomalies=[],
            review_first=[
                review_file("src/utils.py", 30, ["repeated edits"], "MEDIUM"),
            ],
            risk_counts=risk_counts(),
            use_color=False,
        )
        assert "src/utils.py" not in result

    def test_shows_at_most_two_review_files(self) -> None:
        result = render_session_summary(
            session=session(verdict="review_required"),
            anomalies=[],
            review_first=[
                review_file("auth/a.py", 70, ["protected path"]),
                review_file("auth/b.py", 65, ["flagged command"]),
                review_file("auth/c.py", 60, ["repeated edits"]),
            ],
            risk_counts=risk_counts(),
            use_color=False,
        )
        assert "auth/a.py" in result
        assert "auth/b.py" in result
        assert "auth/c.py" not in result


# ---------------------------------------------------------------------------
# 4. High risk
# ---------------------------------------------------------------------------

class TestHighRisk:
    def test_shows_high_risk_label(self) -> None:
        result = render_session_summary(
            session=session(verdict="high_risk"),
            anomalies=[anomaly("tests_failed", "Tests failed", "major")],
            review_first=[],
            risk_counts=risk_counts(risky=1),
            use_color=False,
        )
        assert "High Risk" in result

    def test_shows_top_major_anomaly(self) -> None:
        result = render_session_summary(
            session=session(verdict="high_risk"),
            anomalies=[
                anomaly("tests_failed", "Tests failed", "major"),
                anomaly("dirty_tree", "Uncommitted changes at end", "major"),
            ],
            review_first=[],
            risk_counts=risk_counts(risky=1),
            use_color=False,
        )
        assert "tests failed" in result.lower()


# ---------------------------------------------------------------------------
# 5. Blocked
# ---------------------------------------------------------------------------

class TestBlocked:
    def test_shows_blocked_label(self) -> None:
        result = render_session_summary(
            session=session(verdict="blocked"),
            anomalies=[],
            review_first=[],
            risk_counts=risk_counts(catastrophic=1),
            use_color=False,
        )
        assert "Blocked" in result

    def test_shows_catastrophic_count(self) -> None:
        result = render_session_summary(
            session=session(verdict="blocked"),
            anomalies=[],
            review_first=[],
            risk_counts=risk_counts(catastrophic=2),
            use_color=False,
        )
        assert "2 catastrophic commands blocked" in result


# ---------------------------------------------------------------------------
# 6. Compact mode (pre-commit hook)
# ---------------------------------------------------------------------------

class TestCompactMode:
    def test_single_line(self) -> None:
        result = render_session_summary(
            session=session(verdict="review_required"),
            anomalies=[],
            review_first=[review_file("auth/session.py", 70, ["protected path"])],
            risk_counts=risk_counts(),
            compact=True,
            use_color=False,
        )
        assert len(result.splitlines()) == 1

    def test_contains_verdict(self) -> None:
        result = render_session_summary(
            session=session(verdict="review_required"),
            anomalies=[],
            review_first=[],
            risk_counts=risk_counts(),
            compact=True,
            use_color=False,
        )
        assert "Needs Review" in result

    def test_contains_top_file(self) -> None:
        result = render_session_summary(
            session=session(verdict="review_required"),
            anomalies=[],
            review_first=[review_file("auth/session.py", 70, ["protected path"])],
            risk_counts=risk_counts(),
            compact=True,
            use_color=False,
        )
        assert "session.py" in result

    def test_trusted_compact_contains_trusted(self) -> None:
        result = render_session_summary(
            session=session(verdict="trusted"),
            anomalies=[],
            review_first=[],
            risk_counts=risk_counts(),
            compact=True,
            use_color=False,
        )
        assert "Trusted" in result

    def test_compact_no_review_falls_back_to_anomaly(self) -> None:
        result = render_session_summary(
            session=session(verdict="review_required"),
            anomalies=[anomaly("tests_failed", "Tests failed", "major")],
            review_first=[],
            risk_counts=risk_counts(),
            compact=True,
            use_color=False,
        )
        assert "tests failed" in result.lower()


# ---------------------------------------------------------------------------
# 7. Full mode (tracecode review output)
# ---------------------------------------------------------------------------

class TestFullMode:
    def test_shows_up_to_five_files(self) -> None:
        files = [
            review_file(f"src/file{i}.py", 60 - i * 2, ["repeated edits"])
            for i in range(6)
        ]
        result = render_session_summary(
            session=session(verdict="review_required"),
            anomalies=[],
            review_first=files,
            risk_counts=risk_counts(),
            full=True,
            use_color=False,
        )
        # Top 5 shown, 6th not
        for i in range(5):
            assert f"src/file{i}.py" in result
        assert "src/file5.py" not in result

    def test_shows_all_anomalies(self) -> None:
        result = render_session_summary(
            session=session(verdict="review_required"),
            anomalies=[
                anomaly("tests_failed", "Tests failed", "major"),
                anomaly("dirty_tree", "Uncommitted changes at end", "major"),
                anomaly("no_commits", "No commits made", "minor"),
                anomaly("no_tests", "Tests not checked", "caution"),
            ],
            review_first=[],
            risk_counts=risk_counts(),
            full=True,
            use_color=False,
        )
        assert "Tests failed" in result
        assert "Uncommitted changes at end" in result
        assert "No commits made" in result
        assert "Tests not checked" in result

    def test_shows_medium_priority_files(self) -> None:
        result = render_session_summary(
            session=session(verdict="review_required"),
            anomalies=[],
            review_first=[review_file("src/utils.py", 30, ["repeated edits"], "MEDIUM")],
            risk_counts=risk_counts(),
            full=True,
            use_color=False,
        )
        assert "src/utils.py" in result

    def test_footer_mentions_serve(self) -> None:
        result = render_session_summary(
            session=session(verdict="review_required"),
            anomalies=[],
            review_first=[],
            risk_counts=risk_counts(),
            full=True,
            use_color=False,
        )
        assert "tracecode serve" in result


# ---------------------------------------------------------------------------
# 8. Protected path reason surfaces correctly
# ---------------------------------------------------------------------------

class TestProtectedPathReason:
    def test_protected_path_shown_in_review(self) -> None:
        result = render_session_summary(
            session=session(verdict="review_required"),
            anomalies=[],
            review_first=[
                review_file("infra/deploy.sh", 80, ["protected path", "in final diff"]),
            ],
            risk_counts=risk_counts(),
            use_color=False,
        )
        assert "infra/deploy.sh" in result
        assert "protected path" in result

    def test_in_final_diff_suppressed_in_summary_mode(self) -> None:
        # "in final diff" is suppressed in non-full terminal output
        result = render_session_summary(
            session=session(verdict="review_required"),
            anomalies=[],
            review_first=[
                review_file("infra/deploy.sh", 80, ["protected path", "in final diff"]),
            ],
            risk_counts=risk_counts(),
            full=False,
            use_color=False,
        )
        assert "in final diff" not in result

    def test_in_final_diff_shown_in_full_mode(self) -> None:
        result = render_session_summary(
            session=session(verdict="review_required"),
            anomalies=[],
            review_first=[
                review_file("infra/deploy.sh", 80, ["protected path", "in final diff"]),
            ],
            risk_counts=risk_counts(),
            full=True,
            use_color=False,
        )
        assert "in final diff" in result

    def test_unstable_edits_mapped_to_display_label(self) -> None:
        # Internal key "unstable edits" should render as "most edits discarded"
        result = render_session_summary(
            session=session(verdict="review_required"),
            anomalies=[],
            review_first=[
                review_file("src/auth.py", 55, ["unstable edits"]),
            ],
            risk_counts=risk_counts(),
            full=True,
            use_color=False,
        )
        assert "most edits discarded" in result
        assert "unstable edits" not in result

    def test_in_flagged_command_mapped_to_display_label(self) -> None:
        # Internal key "in flagged command" should render as "flagged command"
        result = render_session_summary(
            session=session(verdict="review_required"),
            anomalies=[],
            review_first=[
                review_file("src/auth.py", 55, ["in flagged command"]),
            ],
            risk_counts=risk_counts(),
            full=True,
            use_color=False,
        )
        assert "flagged command" in result
        assert "in flagged command" not in result


# ---------------------------------------------------------------------------
# 9. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_missing_ended_at(self) -> None:
        # Duration should gracefully omit itself when timing is unavailable
        s = session(verdict="trusted")
        del s["ended_at"]
        result = render_session_summary(
            session=s,
            anomalies=[],
            review_first=[],
            risk_counts=risk_counts(),
            use_color=False,
        )
        assert "Trusted" in result

    def test_missing_verdict_defaults_to_trusted(self) -> None:
        s = session()
        del s["verdict"]
        result = render_session_summary(
            session=s,
            anomalies=[],
            review_first=[],
            risk_counts=risk_counts(),
            use_color=False,
        )
        assert "Trusted" in result

    def test_very_long_path_truncated(self) -> None:
        long_path = "a/b/c/d/e/f/g/h/i/j/k/l/m/n/verylongfilename_that_exceeds_limits.py"
        result = render_session_summary(
            session=session(verdict="review_required"),
            anomalies=[],
            review_first=[review_file(long_path, 70, ["repeated edits"])],
            risk_counts=risk_counts(),
            use_color=False,
        )
        # Ellipsis should appear instead of the full path
        assert "\u2026" in result

    def test_color_disabled(self) -> None:
        result = render_session_summary(
            session=session(verdict="high_risk"),
            anomalies=[],
            review_first=[],
            risk_counts=risk_counts(risky=1),
            use_color=False,
        )
        # No ANSI escape codes
        assert "\033[" not in result

    def test_no_review_files_no_review_section(self) -> None:
        result = render_session_summary(
            session=session(verdict="review_required"),
            anomalies=[anomaly("dirty_tree", "Uncommitted changes at end", "major")],
            review_first=[],
            risk_counts=risk_counts(),
            use_color=False,
        )
        # The "   review    " label only appears when there are files to list.
        # (The verdict label "Needs Review" contains "review" but that is expected.)
        assert "   review    " not in result

    def test_caution_anomaly_not_in_issues_line(self) -> None:
        # Caution-level anomalies (e.g. no_tests) are not shown in the brief summary
        result = render_session_summary(
            session=session(verdict="trusted_with_caveats"),
            anomalies=[anomaly("no_tests", "Tests not checked", "caution")],
            review_first=[],
            risk_counts=risk_counts(),
            use_color=False,
        )
        # No issues line should appear for a caution-only session
        assert "issues" not in result
