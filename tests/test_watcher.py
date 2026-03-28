"""
tests/test_watcher.py — Tests for capture/watcher.py

Covers:
  1. FileChangeHandler ignore logic
  2. aggregate_watch_file — reads JSONL, counts correctly, updates session
  3. Integration test — live Observer writes to JSONL (marked slow)
"""

import io
import json
import time
from pathlib import Path

import pytest

from tracecode.capture.watcher import (
    IGNORE_DIRS,
    IGNORE_EXTENSIONS,
    IGNORE_NAMES,
    FileChangeHandler,
    aggregate_watch_file,
)
from tracecode.config import Config, DEFAULT_IGNORE_DIRS, DEFAULT_IGNORE_EXTENSIONS
from tracecode.db import get_conn, get_session, get_file_touches, init_db
from tracecode.capture.session import start_session


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


def write_jsonl(path: Path, records: list[dict]) -> None:
    """Write a list of dicts to a JSONL file."""
    with open(path, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def make_records(paths: list[str], base_ts: int = 1_000_000_000_000) -> list[dict]:
    """Create fake watcher records for a list of paths."""
    return [{"path": p, "ts": base_ts + i * 100} for i, p in enumerate(paths)]


# ---------------------------------------------------------------------------
# FileChangeHandler — ignore logic
# ---------------------------------------------------------------------------

class TestIgnoreLogic:
    """Test _should_ignore via a handler with a dummy output."""

    def make_handler(self, project_path: str) -> FileChangeHandler:
        return FileChangeHandler(project_path, io.StringIO())

    def test_ignores_git_dir(self, tmp_path: Path) -> None:
        h = self.make_handler(str(tmp_path))
        assert h._should_ignore(str(tmp_path / ".git" / "COMMIT_EDITMSG"))

    def test_ignores_node_modules(self, tmp_path: Path) -> None:
        h = self.make_handler(str(tmp_path))
        assert h._should_ignore(str(tmp_path / "node_modules" / "react" / "index.js"))

    def test_ignores_pycache(self, tmp_path: Path) -> None:
        h = self.make_handler(str(tmp_path))
        assert h._should_ignore(str(tmp_path / "src" / "__pycache__" / "main.cpython-311.pyc"))

    def test_ignores_pyc_extension(self, tmp_path: Path) -> None:
        h = self.make_handler(str(tmp_path))
        assert h._should_ignore(str(tmp_path / "src" / "main.pyc"))

    def test_ignores_swp_file(self, tmp_path: Path) -> None:
        h = self.make_handler(str(tmp_path))
        assert h._should_ignore(str(tmp_path / ".main.py.swp"))

    def test_does_not_ignore_py_file(self, tmp_path: Path) -> None:
        h = self.make_handler(str(tmp_path))
        assert not h._should_ignore(str(tmp_path / "src" / "main.py"))

    def test_does_not_ignore_ts_file(self, tmp_path: Path) -> None:
        h = self.make_handler(str(tmp_path))
        assert not h._should_ignore(str(tmp_path / "src" / "app.ts"))

    def test_does_not_ignore_nested_src(self, tmp_path: Path) -> None:
        h = self.make_handler(str(tmp_path))
        assert not h._should_ignore(str(tmp_path / "src" / "auth" / "login.py"))

    def test_ignores_nested_ignore_dir(self, tmp_path: Path) -> None:
        # venv at any depth should be ignored
        h = self.make_handler(str(tmp_path))
        assert h._should_ignore(str(tmp_path / "backend" / ".venv" / "lib" / "site.py"))

    def test_all_ignore_dirs_covered(self, tmp_path: Path) -> None:
        h = self.make_handler(str(tmp_path))
        for d in IGNORE_DIRS:
            assert h._should_ignore(str(tmp_path / d / "somefile.py")), \
                f"Expected {d} to be ignored"

    def test_all_ignore_extensions_covered(self, tmp_path: Path) -> None:
        h = self.make_handler(str(tmp_path))
        for ext in IGNORE_EXTENSIONS:
            assert h._should_ignore(str(tmp_path / f"file{ext}")), \
                f"Expected extension {ext} to be ignored"

    def test_all_ignore_names_covered(self, tmp_path: Path) -> None:
        h = self.make_handler(str(tmp_path))
        for name in IGNORE_NAMES:
            assert h._should_ignore(str(tmp_path / name)), \
                f"Expected filename {name} to be ignored"


# ---------------------------------------------------------------------------
# FileChangeHandler — record writing
# ---------------------------------------------------------------------------

class TestHandlerRecording:
    def test_records_modified_file(self, tmp_path: Path) -> None:
        output = io.StringIO()
        h = FileChangeHandler(str(tmp_path), output)

        # Simulate a watchdog FileModifiedEvent
        class FakeEvent:
            is_directory = False
            src_path = str(tmp_path / "src" / "main.py")

        h.on_modified(FakeEvent())

        output.seek(0)
        record = json.loads(output.read().strip())
        assert record["path"] == "src/main.py"
        assert isinstance(record["ts"], int)

    def test_skips_directory_events(self, tmp_path: Path) -> None:
        output = io.StringIO()
        h = FileChangeHandler(str(tmp_path), output)

        class FakeDirEvent:
            is_directory = True
            src_path = str(tmp_path / "src")

        h.on_modified(FakeDirEvent())
        output.seek(0)
        assert output.read().strip() == ""

    def test_skips_ignored_file(self, tmp_path: Path) -> None:
        output = io.StringIO()
        h = FileChangeHandler(str(tmp_path), output)

        class FakeEvent:
            is_directory = False
            src_path = str(tmp_path / "node_modules" / "react" / "index.js")

        h.on_modified(FakeEvent())
        output.seek(0)
        assert output.read().strip() == ""

    def test_path_uses_forward_slashes(self, tmp_path: Path) -> None:
        output = io.StringIO()
        h = FileChangeHandler(str(tmp_path), output)

        class FakeEvent:
            is_directory = False
            src_path = str(tmp_path / "src" / "deep" / "file.py")

        h.on_modified(FakeEvent())
        output.seek(0)
        record = json.loads(output.read().strip())
        assert "\\" not in record["path"]
        assert record["path"] == "src/deep/file.py"

    def test_records_moved_destination(self, tmp_path: Path) -> None:
        output = io.StringIO()
        h = FileChangeHandler(str(tmp_path), output)

        class FakeMoveEvent:
            is_directory = False
            src_path = str(tmp_path / "old.py")
            dest_path = str(tmp_path / "new.py")

        h.on_moved(FakeMoveEvent())
        output.seek(0)
        record = json.loads(output.read().strip())
        assert record["path"] == "new.py"


# ---------------------------------------------------------------------------
# aggregate_watch_file
# ---------------------------------------------------------------------------

@pytest.fixture
def db_with_session(tmp_path: Path):
    """Returns (config, session_id) with an open session in the DB."""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    config = make_test_config(db_path)
    session_id = start_session(str(tmp_path), None, None, config)
    return config, session_id


class TestAggregateWatchFile:
    def test_returns_zero_for_missing_file(self, db_with_session, tmp_path: Path) -> None:
        config, session_id = db_with_session
        missing = tmp_path / "watch_nonexistent.jsonl"
        with get_conn(config.db_path) as conn:
            count = aggregate_watch_file(session_id, missing, conn)
        assert count == 0

    def test_returns_zero_for_empty_file(self, db_with_session, tmp_path: Path) -> None:
        config, session_id = db_with_session
        empty = tmp_path / f"watch_{session_id}.jsonl"
        empty.write_text("")
        with get_conn(config.db_path) as conn:
            count = aggregate_watch_file(session_id, empty, conn)
        assert count == 0

    def test_counts_distinct_files(self, db_with_session, tmp_path: Path) -> None:
        config, session_id = db_with_session
        watch_path = tmp_path / f"watch_{session_id}.jsonl"
        records = make_records(["src/a.py", "src/b.py", "src/c.py"])
        write_jsonl(watch_path, records)

        with get_conn(config.db_path) as conn:
            count = aggregate_watch_file(session_id, watch_path, conn)
        assert count == 3

    def test_aggregates_multiple_touches_to_same_file(self, db_with_session, tmp_path: Path) -> None:
        config, session_id = db_with_session
        watch_path = tmp_path / f"watch_{session_id}.jsonl"
        # src/auth.py touched 4 times
        records = make_records(
            ["src/auth.py", "src/auth.py", "src/auth.py", "src/auth.py", "src/other.py"]
        )
        write_jsonl(watch_path, records)

        with get_conn(config.db_path) as conn:
            aggregate_watch_file(session_id, watch_path, conn)
            touches = get_file_touches(conn, session_id)

        auth_touch = next(t for t in touches if t["file_path"] == "src/auth.py")
        assert auth_touch["touch_count"] == 4

        other_touch = next(t for t in touches if t["file_path"] == "src/other.py")
        assert other_touch["touch_count"] == 1

    def test_updates_session_files_touched(self, db_with_session, tmp_path: Path) -> None:
        config, session_id = db_with_session
        watch_path = tmp_path / f"watch_{session_id}.jsonl"
        write_jsonl(watch_path, make_records(["a.py", "b.py", "c.py"]))

        with get_conn(config.db_path) as conn:
            aggregate_watch_file(session_id, watch_path, conn)
            row = get_session(conn, session_id)
        assert row["files_touched"] == 3

    def test_updates_session_hot_files(self, db_with_session, tmp_path: Path) -> None:
        config, session_id = db_with_session
        watch_path = tmp_path / f"watch_{session_id}.jsonl"
        # hot.py touched 5 times (>= 3 = hot), cold.py touched 1 time
        records = make_records(["hot.py"] * 5 + ["cold.py"])
        write_jsonl(watch_path, records)

        with get_conn(config.db_path) as conn:
            aggregate_watch_file(session_id, watch_path, conn)
            row = get_session(conn, session_id)
        assert row["hot_files"] == 1

    def test_hot_files_threshold_is_3(self, db_with_session, tmp_path: Path) -> None:
        config, session_id = db_with_session
        watch_path = tmp_path / f"watch_{session_id}.jsonl"
        # exactly 3 touches = hot
        records = make_records(["threshold.py"] * 3)
        write_jsonl(watch_path, records)

        with get_conn(config.db_path) as conn:
            aggregate_watch_file(session_id, watch_path, conn)
            row = get_session(conn, session_id)
        assert row["hot_files"] == 1

    def test_two_touches_not_hot(self, db_with_session, tmp_path: Path) -> None:
        config, session_id = db_with_session
        watch_path = tmp_path / f"watch_{session_id}.jsonl"
        records = make_records(["notyet.py"] * 2)
        write_jsonl(watch_path, records)

        with get_conn(config.db_path) as conn:
            aggregate_watch_file(session_id, watch_path, conn)
            row = get_session(conn, session_id)
        assert row["hot_files"] == 0

    def test_skips_malformed_lines(self, db_with_session, tmp_path: Path) -> None:
        config, session_id = db_with_session
        watch_path = tmp_path / f"watch_{session_id}.jsonl"
        with open(watch_path, "w") as f:
            f.write('{"path": "good.py", "ts": 1000000000}\n')
            f.write("this is not json\n")
            f.write('{"broken": true}\n')  # missing required keys
            f.write('{"path": "also_good.py", "ts": 1000000001}\n')

        with get_conn(config.db_path) as conn:
            count = aggregate_watch_file(session_id, watch_path, conn)
        assert count == 2

    def test_first_and_last_timestamps(self, db_with_session, tmp_path: Path) -> None:
        config, session_id = db_with_session
        watch_path = tmp_path / f"watch_{session_id}.jsonl"
        records = [
            {"path": "file.py", "ts": 1000},
            {"path": "file.py", "ts": 3000},
            {"path": "file.py", "ts": 2000},
        ]
        write_jsonl(watch_path, records)

        with get_conn(config.db_path) as conn:
            aggregate_watch_file(session_id, watch_path, conn)
            touches = get_file_touches(conn, session_id)

        assert touches[0]["first_touch_at"] == 1000
        assert touches[0]["last_touch_at"] == 3000


# ---------------------------------------------------------------------------
# Integration test — live Observer
# ---------------------------------------------------------------------------

@pytest.mark.slow
class TestWatcherIntegration:
    """
    Starts the real watchdog Observer in a thread, creates files,
    checks the JSONL output. Marked slow — run with: pytest -m slow
    """

    def test_watcher_records_file_creation(self, tmp_path: Path) -> None:
        import threading
        from watchdog.observers import Observer

        output_path = tmp_path / "watch_test.jsonl"
        project_path = tmp_path / "project"
        project_path.mkdir()

        output_file = open(output_path, "a", buffering=1)
        handler = FileChangeHandler(str(project_path), output_file)
        observer = Observer()
        observer.schedule(handler, str(project_path), recursive=True)
        observer.start()

        try:
            # Give observer time to start
            time.sleep(0.2)

            # Create a file inside the watched directory
            (project_path / "hello.py").write_text("print('hello')")

            # Give watchdog time to detect and process the event
            time.sleep(0.3)
        finally:
            observer.stop()
            observer.join(timeout=3)
            output_file.close()

        # Verify at least one record was written
        records = []
        with open(output_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))

        assert len(records) >= 1
        paths = [r["path"] for r in records]
        assert any("hello.py" in p for p in paths)

    def test_watcher_ignores_git_dir(self, tmp_path: Path) -> None:
        import threading
        from watchdog.observers import Observer

        output_path = tmp_path / "watch_test.jsonl"
        project_path = tmp_path / "project"
        project_path.mkdir()
        (project_path / ".git").mkdir()

        output_file = open(output_path, "a", buffering=1)
        handler = FileChangeHandler(str(project_path), output_file)
        observer = Observer()
        observer.schedule(handler, str(project_path), recursive=True)
        observer.start()

        try:
            time.sleep(0.2)
            (project_path / ".git" / "COMMIT_EDITMSG").write_text("init")
            time.sleep(0.3)
        finally:
            observer.stop()
            observer.join(timeout=3)
            output_file.close()

        records = []
        with open(output_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))

        paths = [r["path"] for r in records]
        assert not any(".git" in p for p in paths)
