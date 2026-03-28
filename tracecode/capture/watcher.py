"""
capture/watcher.py — Filesystem watcher for a single session.

Runs as a background subprocess launched by the wrapper script:
    tracecode watch --session-id <uuid> --path <project_dir>

Watches the project directory for file modifications using watchdog.
Appends a JSON record to ~/.tracecode/watch_<session_id>.jsonl for every
relevant file change. Runs until it receives SIGTERM (sent by session-end).

Output format (one JSON object per line):
    {"path": "src/auth.py", "ts": 1711234567890}
    {"path": "tests/test_auth.py", "ts": 1711234568012}

Deliberately simple: no deduplication, no batching, no real-time analysis.
Aggregation happens once, post-session, in session.py.
"""

import json
import os
import signal
import threading
import time
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer


# ---------------------------------------------------------------------------
# Ignore lists — applied at any directory depth
# ---------------------------------------------------------------------------

IGNORE_DIRS: frozenset[str] = frozenset({
    ".git", "node_modules", "__pycache__", ".next", "dist",
    "build", "target", ".venv", "venv", ".pytest_cache",
    ".mypy_cache", "coverage", ".turbo", ".idea", ".vscode",
})

IGNORE_EXTENSIONS: frozenset[str] = frozenset({
    ".pyc", ".pyo", ".swp", ".swo", ".lock", ".orig", ".bak",
})

# Exact filenames to ignore (these are names, not extensions)
IGNORE_NAMES: frozenset[str] = frozenset({
    ".DS_Store",
})


# ---------------------------------------------------------------------------
# Event handler
# ---------------------------------------------------------------------------

class FileChangeHandler(FileSystemEventHandler):
    """
    Writes a JSON record to the output file for every relevant file change.
    Ignores directories, ignored dir names, and ignored extensions.
    """

    def __init__(self, project_path: str, output_file) -> None:
        self.project_path = str(Path(project_path).resolve())
        self.output_file = output_file

    # watchdog fires on_modified for edits and on_created for new files.
    # on_moved covers Save As / atomic saves (many editors write to a temp file then rename).
    def on_modified(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._record(event.src_path)

    def on_created(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._record(event.src_path)

    def on_moved(self, event: FileSystemEvent) -> None:
        # Record the destination — that's the file that now exists
        if not event.is_directory:
            self._record(event.dest_path)

    def _record(self, abs_path: str) -> None:
        if self._should_ignore(abs_path):
            return

        try:
            rel_path = os.path.relpath(abs_path, self.project_path)
        except ValueError:
            # Can happen on Windows with different drives; skip
            return

        # Normalise to forward slashes so paths are consistent cross-platform
        rel_path = rel_path.replace(os.sep, "/")

        record = {"path": rel_path, "ts": int(time.time() * 1000)}
        try:
            self.output_file.write(json.dumps(record) + "\n")
            self.output_file.flush()
        except OSError:
            pass  # output file closed — watcher is shutting down

    def _should_ignore(self, abs_path: str) -> bool:
        """Return True if this path should be skipped."""
        path = Path(abs_path)

        # Check every path component against the ignore dir list
        for part in path.parts:
            if part in IGNORE_DIRS:
                return True

        # Check exact filename (e.g. .DS_Store)
        if path.name in IGNORE_NAMES:
            return True

        # Check file extension
        if path.suffix.lower() in IGNORE_EXTENSIONS:
            return True

        return False


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_watcher(session_id: str, project_path: str, tracecode_dir: Path) -> None:
    """
    Start watching project_path and write events to a JSONL file.
    Blocks until SIGTERM or SIGINT is received.

    Called by `tracecode watch` CLI command.
    The wrapper script sends SIGTERM when the claude session ends.
    """
    output_path = tracecode_dir / f"watch_{session_id}.jsonl"
    project_path = str(Path(project_path).resolve())

    stop_event = threading.Event()

    def _handle_signal(signum, frame):
        stop_event.set()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    with open(output_path, "a", buffering=1) as output_file:  # line-buffered
        handler = FileChangeHandler(project_path, output_file)
        observer = Observer()
        observer.schedule(handler, project_path, recursive=True)
        observer.start()

        try:
            # Block until a signal tells us to stop
            stop_event.wait()
        finally:
            observer.stop()
            observer.join(timeout=3)
            # output_file is flushed and closed by the context manager


# ---------------------------------------------------------------------------
# Aggregation — called by session-end after the watcher process is killed
# ---------------------------------------------------------------------------

def aggregate_watch_file(
    session_id: str,
    watch_path: Path,
    conn,
) -> int:
    """
    Read the JSONL file written by the watcher, aggregate by file path,
    insert rows into file_touches, and update sessions.files_touched / hot_files.

    Returns the number of distinct files touched (0 if no data).
    Handles missing or empty files gracefully.
    """
    from tracecode.db import bulk_insert_file_touches, update_session

    if not watch_path.exists():
        return 0

    # Parse JSONL — skip malformed lines silently
    touches: dict[str, dict] = {}
    try:
        with open(watch_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    path: str = record["path"]
                    ts: int = record["ts"]
                except (json.JSONDecodeError, KeyError):
                    continue

                if path not in touches:
                    touches[path] = {"count": 0, "first_ts": ts, "last_ts": ts}
                touches[path]["count"] += 1
                touches[path]["last_ts"] = max(touches[path]["last_ts"], ts)
                touches[path]["first_ts"] = min(touches[path]["first_ts"], ts)
    except OSError:
        return 0

    if not touches:
        return 0

    # Insert into file_touches table
    rows = [
        {
            "session_id": session_id,
            "file_path": path,
            "touch_count": data["count"],
            "first_touch_at": data["first_ts"],
            "last_touch_at": data["last_ts"],
        }
        for path, data in touches.items()
    ]
    bulk_insert_file_touches(conn, rows)

    # Update session-level aggregates
    hot_files = sum(1 for d in touches.values() if d["count"] >= 3)
    update_session(conn, session_id,
                   files_touched=len(touches),
                   hot_files=hot_files)

    return len(touches)
