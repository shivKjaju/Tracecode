"""
tests/test_db.py — Tests for db.py

All tests use a temporary database file via pytest's tmp_path fixture.
No test touches ~/.tracecode or any real user data.
"""

import sqlite3
import time
import uuid
from pathlib import Path

import pytest

from tracecode.db import (
    bulk_insert_file_touches,
    count_sessions,
    get_file_touches,
    get_session,
    init_db,
    get_conn,
    insert_file_touch,
    insert_session,
    list_sessions,
    update_file_touch_persisted,
    update_session,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Create and initialize a fresh test database. Never touches ~/.tracecode."""
    path = tmp_path / "test_tracecode.db"
    init_db(path)
    return path


def make_session(override: dict | None = None) -> dict:
    """Return a minimal valid session dict, optionally with overrides."""
    base = {
        "id": str(uuid.uuid4()),
        "started_at": int(time.time()),
        "project_path": "/tmp/testproject",
        "project_name": "testproject",
        "git_branch": "main",
        "git_commit_before": "abc123",
    }
    if override:
        base.update(override)
    return base


def make_file_touch(session_id: str, file_path: str = "src/main.py", touch_count: int = 1) -> dict:
    """Return a minimal valid file_touch dict."""
    now_ms = int(time.time() * 1000)
    return {
        "session_id": session_id,
        "file_path": file_path,
        "touch_count": touch_count,
        "first_touch_at": now_ms,
        "last_touch_at": now_ms + (touch_count * 1000),
    }


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------

class TestInit:
    def test_creates_database_file(self, tmp_path: Path) -> None:
        path = tmp_path / "new.db"
        assert not path.exists()
        init_db(path)
        assert path.exists()

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        path = tmp_path / "nested" / "dirs" / "tracecode.db"
        init_db(path)
        assert path.exists()

    def test_idempotent_on_existing_db(self, db_path: Path) -> None:
        # Calling init_db twice must not raise or corrupt the database
        init_db(db_path)
        init_db(db_path)
        with get_conn(db_path) as conn:
            # Basic query should still work
            conn.execute("SELECT COUNT(*) FROM sessions").fetchone()

    def test_sessions_table_exists(self, db_path: Path) -> None:
        with get_conn(db_path) as conn:
            tables = {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        assert "sessions" in tables

    def test_file_touches_table_exists(self, db_path: Path) -> None:
        with get_conn(db_path) as conn:
            tables = {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        assert "file_touches" in tables

    def test_wal_mode_enabled(self, db_path: Path) -> None:
        with get_conn(db_path) as conn:
            result = conn.execute("PRAGMA journal_mode").fetchone()
        assert result[0] == "wal"

    def test_foreign_keys_enabled(self, db_path: Path) -> None:
        with get_conn(db_path) as conn:
            result = conn.execute("PRAGMA foreign_keys").fetchone()
        assert result[0] == 1


# ---------------------------------------------------------------------------
# Session CRUD tests
# ---------------------------------------------------------------------------

class TestInsertSession:
    def test_insert_and_retrieve(self, db_path: Path) -> None:
        session = make_session()
        with get_conn(db_path) as conn:
            returned_id = insert_session(conn, session)
            fetched = get_session(conn, session["id"])

        assert returned_id == session["id"]
        assert fetched is not None
        assert fetched["id"] == session["id"]
        assert fetched["project_name"] == "testproject"
        assert fetched["started_at"] == session["started_at"]

    def test_optional_git_fields_default_to_none(self, db_path: Path) -> None:
        session = make_session({"git_branch": None, "git_commit_before": None})
        with get_conn(db_path) as conn:
            insert_session(conn, session)
            fetched = get_session(conn, session["id"])

        assert fetched["git_branch"] is None
        assert fetched["git_commit_before"] is None

    def test_score_fields_start_as_none(self, db_path: Path) -> None:
        session = make_session()
        with get_conn(db_path) as conn:
            insert_session(conn, session)
            fetched = get_session(conn, session["id"])

        # All post-session fields should be NULL initially
        for field in ("ended_at", "wandering_score", "quality_score",
                      "outcome_score", "auto_outcome", "test_outcome"):
            assert fetched[field] is None, f"Expected {field} to be None"

    def test_duplicate_id_raises(self, db_path: Path) -> None:
        session = make_session()
        with get_conn(db_path) as conn:
            insert_session(conn, session)
        with pytest.raises(sqlite3.IntegrityError):
            with get_conn(db_path) as conn:
                insert_session(conn, session)  # same id


class TestGetSession:
    def test_returns_none_for_missing_id(self, db_path: Path) -> None:
        with get_conn(db_path) as conn:
            result = get_session(conn, "nonexistent-id")
        assert result is None

    def test_returns_dict_not_row(self, db_path: Path) -> None:
        session = make_session()
        with get_conn(db_path) as conn:
            insert_session(conn, session)
            fetched = get_session(conn, session["id"])
        # Must be a plain dict, not a sqlite3.Row
        assert isinstance(fetched, dict)


class TestUpdateSession:
    def test_update_single_field(self, db_path: Path) -> None:
        session = make_session()
        end_time = int(time.time()) + 300
        with get_conn(db_path) as conn:
            insert_session(conn, session)
            update_session(conn, session["id"], ended_at=end_time)
            fetched = get_session(conn, session["id"])
        assert fetched["ended_at"] == end_time

    def test_update_multiple_fields(self, db_path: Path) -> None:
        session = make_session()
        with get_conn(db_path) as conn:
            insert_session(conn, session)
            update_session(
                conn, session["id"],
                ended_at=int(time.time()) + 100,
                wandering_score=0.4,
                quality_score=0.75,
                outcome_score=3,
                auto_outcome="success",
            )
            fetched = get_session(conn, session["id"])

        assert fetched["wandering_score"] == pytest.approx(0.4)
        assert fetched["quality_score"] == pytest.approx(0.75)
        assert fetched["outcome_score"] == 3
        assert fetched["auto_outcome"] == "success"

    def test_update_rejects_immutable_columns(self, db_path: Path) -> None:
        session = make_session()
        with get_conn(db_path) as conn:
            insert_session(conn, session)
        with pytest.raises(ValueError, match="read-only"):
            with get_conn(db_path) as conn:
                update_session(conn, session["id"], id="newid")

    def test_update_with_no_fields_is_noop(self, db_path: Path) -> None:
        session = make_session()
        with get_conn(db_path) as conn:
            insert_session(conn, session)
            # Should not raise
            update_session(conn, session["id"])
            fetched = get_session(conn, session["id"])
        assert fetched["id"] == session["id"]

    def test_persistence_reliable_stored_as_integer(self, db_path: Path) -> None:
        session = make_session()
        with get_conn(db_path) as conn:
            insert_session(conn, session)
            update_session(conn, session["id"], persistence_reliable=1, persistence_rate=0.8)
            fetched = get_session(conn, session["id"])
        assert fetched["persistence_reliable"] == 1
        assert fetched["persistence_rate"] == pytest.approx(0.8)


class TestListSessions:
    def test_returns_empty_list_when_no_sessions(self, db_path: Path) -> None:
        with get_conn(db_path) as conn:
            result = list_sessions(conn)
        assert result == []

    def test_returns_newest_first(self, db_path: Path) -> None:
        now = int(time.time())
        old = make_session({"id": str(uuid.uuid4()), "started_at": now - 3600})
        new = make_session({"id": str(uuid.uuid4()), "started_at": now})
        middle = make_session({"id": str(uuid.uuid4()), "started_at": now - 1800})

        with get_conn(db_path) as conn:
            insert_session(conn, old)
            insert_session(conn, new)
            insert_session(conn, middle)
            result = list_sessions(conn)

        assert result[0]["id"] == new["id"]
        assert result[1]["id"] == middle["id"]
        assert result[2]["id"] == old["id"]

    def test_limit_and_offset(self, db_path: Path) -> None:
        now = int(time.time())
        sessions = [
            make_session({"id": str(uuid.uuid4()), "started_at": now - i})
            for i in range(5)
        ]
        with get_conn(db_path) as conn:
            for s in sessions:
                insert_session(conn, s)
            first_two = list_sessions(conn, limit=2, offset=0)
            next_two = list_sessions(conn, limit=2, offset=2)

        assert len(first_two) == 2
        assert len(next_two) == 2
        assert first_two[0]["id"] != next_two[0]["id"]

    def test_returns_list_of_dicts(self, db_path: Path) -> None:
        session = make_session()
        with get_conn(db_path) as conn:
            insert_session(conn, session)
            result = list_sessions(conn)
        assert isinstance(result, list)
        assert isinstance(result[0], dict)


class TestCountSessions:
    def test_count_zero(self, db_path: Path) -> None:
        with get_conn(db_path) as conn:
            assert count_sessions(conn) == 0

    def test_count_increments(self, db_path: Path) -> None:
        with get_conn(db_path) as conn:
            insert_session(conn, make_session())
            insert_session(conn, make_session())
            assert count_sessions(conn) == 2


# ---------------------------------------------------------------------------
# File touch CRUD tests
# ---------------------------------------------------------------------------

class TestFileTouches:
    def test_insert_and_retrieve(self, db_path: Path) -> None:
        session = make_session()
        touch = make_file_touch(session["id"], "src/auth.py", touch_count=3)

        with get_conn(db_path) as conn:
            insert_session(conn, session)
            insert_file_touch(conn, touch)
            touches = get_file_touches(conn, session["id"])

        assert len(touches) == 1
        assert touches[0]["file_path"] == "src/auth.py"
        assert touches[0]["touch_count"] == 3
        assert touches[0]["persisted"] is None

    def test_bulk_insert(self, db_path: Path) -> None:
        session = make_session()
        touches = [
            make_file_touch(session["id"], f"src/file_{i}.py", touch_count=i + 1)
            for i in range(5)
        ]

        with get_conn(db_path) as conn:
            insert_session(conn, session)
            bulk_insert_file_touches(conn, touches)
            result = get_file_touches(conn, session["id"])

        assert len(result) == 5

    def test_sorted_by_touch_count_descending(self, db_path: Path) -> None:
        session = make_session()
        touches = [
            make_file_touch(session["id"], "low.py", touch_count=1),
            make_file_touch(session["id"], "high.py", touch_count=5),
            make_file_touch(session["id"], "mid.py", touch_count=3),
        ]

        with get_conn(db_path) as conn:
            insert_session(conn, session)
            bulk_insert_file_touches(conn, touches)
            result = get_file_touches(conn, session["id"])

        assert result[0]["file_path"] == "high.py"
        assert result[1]["file_path"] == "mid.py"
        assert result[2]["file_path"] == "low.py"

    def test_returns_empty_for_unknown_session(self, db_path: Path) -> None:
        with get_conn(db_path) as conn:
            result = get_file_touches(conn, "nonexistent-session-id")
        assert result == []

    def test_update_persisted_flag(self, db_path: Path) -> None:
        session = make_session()
        touch = make_file_touch(session["id"])

        with get_conn(db_path) as conn:
            insert_session(conn, session)
            insert_file_touch(conn, touch)
            touch_id = conn.execute(
                "SELECT id FROM file_touches WHERE session_id = ?", (session["id"],)
            ).fetchone()["id"]
            update_file_touch_persisted(conn, touch_id, True)
            result = get_file_touches(conn, session["id"])

        assert result[0]["persisted"] == 1

    def test_foreign_key_constraint(self, db_path: Path) -> None:
        """file_touches must reference a real session."""
        touch = make_file_touch("nonexistent-session-id")
        with pytest.raises(sqlite3.IntegrityError):
            with get_conn(db_path) as conn:
                insert_file_touch(conn, touch)

    def test_cascade_delete(self, db_path: Path) -> None:
        """Deleting a session should cascade-delete its file touches."""
        session = make_session()
        touch = make_file_touch(session["id"])

        with get_conn(db_path) as conn:
            insert_session(conn, session)
            insert_file_touch(conn, touch)
            conn.execute("DELETE FROM sessions WHERE id = ?", (session["id"],))
            remaining = get_file_touches(conn, session["id"])

        assert remaining == []


# ---------------------------------------------------------------------------
# Connection behavior tests
# ---------------------------------------------------------------------------

class TestGetConn:
    def test_rollback_on_exception(self, db_path: Path) -> None:
        session = make_session()
        try:
            with get_conn(db_path) as conn:
                insert_session(conn, session)
                raise RuntimeError("simulated error")
        except RuntimeError:
            pass

        # Session should NOT have been committed
        with get_conn(db_path) as conn:
            result = get_session(conn, session["id"])
        assert result is None

    def test_commit_on_clean_exit(self, db_path: Path) -> None:
        session = make_session()
        with get_conn(db_path) as conn:
            insert_session(conn, session)
        # Open a new connection to verify the commit persisted
        with get_conn(db_path) as conn:
            result = get_session(conn, session["id"])
        assert result is not None
