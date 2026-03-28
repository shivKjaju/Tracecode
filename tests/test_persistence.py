"""
tests/test_persistence.py — Tests for analysis/persistence.py

Tests compute_persistence() with real git repos and watcher data.
Fixtures (git_repo, plain_dir) come from tests/conftest.py.
"""

import json
import subprocess
import time
from pathlib import Path

import pytest

from tracecode.analysis.persistence import compute_persistence
from tracecode.capture.git import get_head_sha
from tracecode.capture.session import start_session
from tracecode.config import Config, DEFAULT_IGNORE_DIRS, DEFAULT_IGNORE_EXTENSIONS
from tracecode.db import get_conn, get_file_touches, init_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_test_config(db_path: Path) -> Config:
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


def git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


def commit_file(repo: Path, filename: str, content: str) -> None:
    (repo / filename).write_text(content)
    git(["add", filename], repo)
    git(["commit", "-m", f"add {filename}"], repo)


def seed_file_touches(conn, session_id: str, files: list[str]) -> None:
    """Insert fake file_touch rows for the given file paths."""
    from tracecode.db import bulk_insert_file_touches
    now_ms = int(time.time() * 1000)
    rows = [
        {
            "session_id": session_id,
            "file_path": f,
            "touch_count": 1,
            "first_touch_at": now_ms,
            "last_touch_at": now_ms,
        }
        for f in files
    ]
    bulk_insert_file_touches(conn, rows)


@pytest.fixture
def db_config(tmp_path: Path) -> Config:
    db_path = tmp_path / "test.db"
    init_db(db_path)
    return make_test_config(db_path)


# ---------------------------------------------------------------------------
# compute_persistence
# ---------------------------------------------------------------------------

class TestComputePersistence:
    def test_returns_none_unreliable_for_plain_dir(self, plain_dir: Path, db_config: Config) -> None:
        with get_conn(db_config.db_path) as conn:
            session_id = start_session(str(plain_dir), None, None, db_config)
            rate, reliable = compute_persistence(session_id, plain_dir, None, conn)
        assert rate is None
        assert reliable is False

    def test_returns_none_unreliable_without_start_sha(self, git_repo: Path, db_config: Config) -> None:
        with get_conn(db_config.db_path) as conn:
            session_id = start_session(str(git_repo), None, None, db_config)
            rate, reliable = compute_persistence(session_id, git_repo, None, conn)
        assert rate is None
        assert reliable is False

    def test_returns_none_when_no_file_touches(self, git_repo: Path, db_config: Config) -> None:
        start_sha = get_head_sha(git_repo)
        with get_conn(db_config.db_path) as conn:
            session_id = start_session(str(git_repo), None, start_sha, db_config)
            # No file touches inserted
            rate, reliable = compute_persistence(session_id, git_repo, start_sha, conn)
        assert rate is None
        assert reliable is False

    def test_full_persistence_when_all_files_committed(self, git_repo: Path, db_config: Config) -> None:
        start_sha = get_head_sha(git_repo)

        # Commit a file during the "session"
        commit_file(git_repo, "feature.py", "x = 1")

        with get_conn(db_config.db_path) as conn:
            session_id = start_session(str(git_repo), None, start_sha, db_config)
            seed_file_touches(conn, session_id, ["feature.py"])
            rate, reliable = compute_persistence(session_id, git_repo, start_sha, conn)

        assert reliable is True
        assert rate == 1.0

    def test_zero_persistence_when_all_changes_reverted(self, git_repo: Path, db_config: Config) -> None:
        start_sha = get_head_sha(git_repo)

        # Modify a file but then revert it (no net change)
        (git_repo / "README.md").write_text("temporary change")
        git(["checkout", "README.md"], git_repo)  # revert

        with get_conn(db_config.db_path) as conn:
            session_id = start_session(str(git_repo), None, start_sha, db_config)
            seed_file_touches(conn, session_id, ["README.md"])
            rate, reliable = compute_persistence(session_id, git_repo, start_sha, conn)

        assert reliable is True
        assert rate == 0.0

    def test_partial_persistence(self, git_repo: Path, db_config: Config) -> None:
        start_sha = get_head_sha(git_repo)

        # Commit one file, revert another
        commit_file(git_repo, "kept.py", "x = 1")
        (git_repo / "README.md").write_text("temp")
        git(["checkout", "README.md"], git_repo)

        with get_conn(db_config.db_path) as conn:
            session_id = start_session(str(git_repo), None, start_sha, db_config)
            seed_file_touches(conn, session_id, ["kept.py", "README.md"])
            rate, reliable = compute_persistence(session_id, git_repo, start_sha, conn)

        assert reliable is True
        assert rate == 0.5  # 1 of 2 files persisted

    def test_uncommitted_dirty_file_counts_as_persisted(self, git_repo: Path, db_config: Config) -> None:
        start_sha = get_head_sha(git_repo)

        # Modify a file but don't commit it
        (git_repo / "README.md").write_text("modified but not committed")

        with get_conn(db_config.db_path) as conn:
            session_id = start_session(str(git_repo), None, start_sha, db_config)
            seed_file_touches(conn, session_id, ["README.md"])
            rate, reliable = compute_persistence(session_id, git_repo, start_sha, conn)

        assert reliable is True
        assert rate == 1.0  # dirty file = persisted

    def test_updates_persisted_flag_on_file_touches(self, git_repo: Path, db_config: Config) -> None:
        start_sha = get_head_sha(git_repo)
        commit_file(git_repo, "kept.py", "x = 1")

        with get_conn(db_config.db_path) as conn:
            session_id = start_session(str(git_repo), None, start_sha, db_config)
            seed_file_touches(conn, session_id, ["kept.py", "README.md"])
            compute_persistence(session_id, git_repo, start_sha, conn)
            touches = get_file_touches(conn, session_id)

        touch_by_path = {t["file_path"]: t for t in touches}
        assert touch_by_path["kept.py"]["persisted"] == 1
        assert touch_by_path["README.md"]["persisted"] == 0

    def test_rate_rounds_to_3_decimal_places(self, git_repo: Path, db_config: Config) -> None:
        start_sha = get_head_sha(git_repo)
        # Commit 1 of 3 files → rate = 0.333...
        commit_file(git_repo, "a.py", "a")

        with get_conn(db_config.db_path) as conn:
            session_id = start_session(str(git_repo), None, start_sha, db_config)
            seed_file_touches(conn, session_id, ["a.py", "b.py", "c.py"])
            rate, _ = compute_persistence(session_id, git_repo, start_sha, conn)

        assert rate == pytest.approx(0.333, abs=0.001)
