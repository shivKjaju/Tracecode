"""
tests/test_session.py — Tests for capture/session.py

Uses a temporary DB via a test Config. Never touches ~/.tracecode.
"""

import time
from pathlib import Path

import pytest

from tracecode.capture.session import end_session, start_session
from tracecode.config import Config, DEFAULT_IGNORE_DIRS, DEFAULT_IGNORE_EXTENSIONS
from tracecode.db import get_conn, get_session, init_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_test_config(db_path: Path) -> Config:
    """Return a Config that points at a temp DB. All other fields use defaults."""
    return Config(
        db_path=db_path,
        server_port=7842,
        claude_binary="",
        log_file=db_path.parent / "test.log",
        test_command=None,
        test_timeout=30,
        watch_ignore_dirs=DEFAULT_IGNORE_DIRS,
        watch_ignore_extensions=DEFAULT_IGNORE_EXTENSIONS,
    )


@pytest.fixture
def config(tmp_path: Path) -> Config:
    """Initialized test config with a fresh DB."""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    return make_test_config(db_path)


# ---------------------------------------------------------------------------
# start_session
# ---------------------------------------------------------------------------

class TestStartSession:
    def test_returns_uuid_string(self, config: Config, tmp_path: Path) -> None:
        session_id = start_session(str(tmp_path), None, None, config)
        # UUID v4: 32 hex chars + 4 dashes = 36 chars
        assert len(session_id) == 36
        assert session_id.count("-") == 4

    def test_creates_db_row(self, config: Config, tmp_path: Path) -> None:
        session_id = start_session(str(tmp_path), "main", "abc123", config)
        with get_conn(config.db_path) as conn:
            row = get_session(conn, session_id)
        assert row is not None

    def test_row_has_correct_project_fields(self, config: Config, tmp_path: Path) -> None:
        session_id = start_session(str(tmp_path), "main", "abc123", config)
        with get_conn(config.db_path) as conn:
            row = get_session(conn, session_id)
        assert row["project_path"] == str(tmp_path.resolve())
        assert row["project_name"] == tmp_path.name

    def test_row_has_git_fields(self, config: Config, tmp_path: Path) -> None:
        session_id = start_session(str(tmp_path), "feature/auth", "deadbeef", config)
        with get_conn(config.db_path) as conn:
            row = get_session(conn, session_id)
        assert row["git_branch"] == "feature/auth"
        assert row["git_commit_before"] == "deadbeef"

    def test_row_started_at_is_recent(self, config: Config, tmp_path: Path) -> None:
        before = int(time.time())
        session_id = start_session(str(tmp_path), None, None, config)
        after = int(time.time())
        with get_conn(config.db_path) as conn:
            row = get_session(conn, session_id)
        assert before <= row["started_at"] <= after

    def test_row_ended_at_is_null(self, config: Config, tmp_path: Path) -> None:
        session_id = start_session(str(tmp_path), None, None, config)
        with get_conn(config.db_path) as conn:
            row = get_session(conn, session_id)
        assert row["ended_at"] is None

    def test_none_git_fields_stored_as_null(self, config: Config, tmp_path: Path) -> None:
        session_id = start_session(str(tmp_path), None, None, config)
        with get_conn(config.db_path) as conn:
            row = get_session(conn, session_id)
        assert row["git_branch"] is None
        assert row["git_commit_before"] is None

    def test_empty_string_git_fields_stored_as_null(self, config: Config, tmp_path: Path) -> None:
        # The wrapper passes empty strings when git is unavailable
        session_id = start_session(str(tmp_path), "", "", config)
        with get_conn(config.db_path) as conn:
            row = get_session(conn, session_id)
        assert row["git_branch"] is None
        assert row["git_commit_before"] is None

    def test_resolves_relative_path(self, config: Config, tmp_path: Path) -> None:
        # project_path should always be stored as absolute
        session_id = start_session(str(tmp_path), None, None, config)
        with get_conn(config.db_path) as conn:
            row = get_session(conn, session_id)
        assert Path(row["project_path"]).is_absolute()

    def test_two_sessions_get_different_ids(self, config: Config, tmp_path: Path) -> None:
        id1 = start_session(str(tmp_path), None, None, config)
        id2 = start_session(str(tmp_path), None, None, config)
        assert id1 != id2


# ---------------------------------------------------------------------------
# end_session
# ---------------------------------------------------------------------------

class TestEndSession:
    def test_sets_ended_at(self, config: Config, tmp_path: Path) -> None:
        session_id = start_session(str(tmp_path), None, None, config)
        before = int(time.time())
        end_session(session_id, 0, config)
        after = int(time.time())
        with get_conn(config.db_path) as conn:
            row = get_session(conn, session_id)
        assert before <= row["ended_at"] <= after

    def test_sets_exit_code_zero(self, config: Config, tmp_path: Path) -> None:
        session_id = start_session(str(tmp_path), None, None, config)
        end_session(session_id, 0, config)
        with get_conn(config.db_path) as conn:
            row = get_session(conn, session_id)
        assert row["claude_exit_code"] == 0

    def test_sets_exit_code_nonzero(self, config: Config, tmp_path: Path) -> None:
        session_id = start_session(str(tmp_path), None, None, config)
        end_session(session_id, 1, config)
        with get_conn(config.db_path) as conn:
            row = get_session(conn, session_id)
        assert row["claude_exit_code"] == 1

    def test_scores_remain_null_on_day2(self, config: Config, tmp_path: Path) -> None:
        # Post-session analysis is not wired in yet — all score fields stay NULL
        session_id = start_session(str(tmp_path), None, None, config)
        end_session(session_id, 0, config)
        with get_conn(config.db_path) as conn:
            row = get_session(conn, session_id)
        for field in ("wandering_score", "quality_score", "outcome_score", "auto_outcome"):
            assert row[field] is None, f"Expected {field} to be NULL on Day 2"

    def test_does_not_overwrite_other_fields(self, config: Config, tmp_path: Path) -> None:
        session_id = start_session(str(tmp_path), "main", "abc123", config)
        end_session(session_id, 0, config)
        with get_conn(config.db_path) as conn:
            row = get_session(conn, session_id)
        # start fields should be untouched
        assert row["git_branch"] == "main"
        assert row["git_commit_before"] == "abc123"
        assert row["project_name"] == tmp_path.name


# ---------------------------------------------------------------------------
# Round-trip: start → end → read
# ---------------------------------------------------------------------------

class TestRoundTrip:
    def test_full_lifecycle(self, config: Config, tmp_path: Path) -> None:
        # Start
        session_id = start_session(str(tmp_path), "main", "sha123", config)
        with get_conn(config.db_path) as conn:
            mid = get_session(conn, session_id)
        assert mid["ended_at"] is None

        # End
        end_session(session_id, 0, config)
        with get_conn(config.db_path) as conn:
            final = get_session(conn, session_id)

        assert final["ended_at"] is not None
        assert final["ended_at"] >= final["started_at"]
        assert final["claude_exit_code"] == 0
        assert final["git_branch"] == "main"
