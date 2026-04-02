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

Aggregation happens once, post-session, in session.py.
At aggregation time, files matched by .gitignore or a transient-file filter
are excluded from all metrics and counted separately as ignored_touches.
"""

import collections
import json
import os
import signal
import subprocess
import threading
import time
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer


# ---------------------------------------------------------------------------
# Ignore lists — two tiers, applied at different times
# ---------------------------------------------------------------------------
#
# Why two tiers?
#
# TIER 1 — watch-time (applied inside FileChangeHandler._should_ignore):
#   Filters events as they arrive from the OS. Only catches obvious noise like
#   compiled bytecode, editor swap files, and build artifact directories.
#   We want this to be fast and permissive — it's cheaper to log an extra event
#   and discard it later than to miss a real file change.
#
# TIER 2 — aggregation-time (_is_transient + gitignore check, applied in
#   aggregate_watch_file after the session ends):
#   A second, more careful pass that removes lock files and generated files.
#   These ARE real filesystem writes, but they carry no signal about what the
#   agent was thinking — package-lock.json changes when you install anything.
#   We also run `git check-ignore` here to respect the project's own .gitignore.
#   We can afford to be thorough here because it runs once, not per-event.

IGNORE_DIRS: frozenset[str] = frozenset({
    ".git", "node_modules", "__pycache__", ".next", "dist",
    "build", "target", ".venv", "venv", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", "coverage", ".turbo",
    ".idea", ".vscode", ".eggs", "htmlcov", ".tox",
})

IGNORE_EXTENSIONS: frozenset[str] = frozenset({
    # Python bytecode
    ".pyc", ".pyo", ".pyd",
    # Editor swap / backup
    ".swp", ".swo", ".orig", ".bak",
    # Compiled objects
    ".o", ".so", ".dylib", ".class",
    # Source maps
    ".map",
    # macOS metadata — also covered by IGNORE_NAMES for the bare filename
    ".ds_store",
})

IGNORE_NAMES: frozenset[str] = frozenset({
    ".DS_Store",
    "Thumbs.db",
})

# Tier 2: lock files and generated files — filtered at aggregation time.
# These are real filesystem writes but carry no useful signal about agent behaviour.
_AGGREGATION_IGNORE_EXTENSIONS: frozenset[str] = frozenset({
    ".lock",           # package-lock.json, Pipfile.lock, poetry.lock
    ".d.ts",           # generated TypeScript declarations
    ".min.js",         # minified JS
    ".min.css",        # minified CSS
})

_AGGREGATION_IGNORE_NAMES: frozenset[str] = frozenset({
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "Pipfile.lock",
    "poetry.lock",
    "Cargo.lock",
    "go.sum",
    "composer.lock",
})


# ---------------------------------------------------------------------------
# Event handler
# ---------------------------------------------------------------------------

class FileChangeHandler(FileSystemEventHandler):
    def __init__(
        self,
        project_path: str,
        output_file,
        session_id: str = "",
        db_path: Path | None = None,
    ) -> None:
        self.project_path = str(Path(project_path).resolve())
        self.output_file = output_file
        self.session_id = session_id
        self.db_path = db_path
        # Runtime threshold tracking (in-memory only, never written to JSONL)
        self._path_counts: dict[str, int] = {}
        self._path_churn_warned: set[str] = set()
        self._blast_radius_fired: bool = False
        self._sensitive_warned: set[str] = set()
        # Rolling window for blast radius: (timestamp_ms, rel_path) pairs
        self._recent_events: collections.deque = collections.deque(maxlen=2000)

    def on_modified(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._record(event.src_path)

    def on_created(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._record(event.src_path)

    def on_moved(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._record(event.dest_path)

    def _record(self, abs_path: str) -> None:
        if self._should_ignore(abs_path):
            return
        try:
            rel_path = os.path.relpath(abs_path, self.project_path)
        except ValueError:
            return
        rel_path = rel_path.replace(os.sep, "/")
        now_ms = int(time.time() * 1000)
        record = {"path": rel_path, "ts": now_ms}
        try:
            self.output_file.write(json.dumps(record) + "\n")
            self.output_file.flush()
        except OSError:
            pass
        if self.session_id and self.db_path:
            self._check_thresholds(rel_path, now_ms)

    def _check_thresholds(self, rel_path: str, now_ms: int) -> None:
        self._path_counts[rel_path] = self._path_counts.get(rel_path, 0) + 1
        self._recent_events.append((now_ms, rel_path))

        # Sensitive file — fire a warning the first time a .env / config / cert
        # file is touched. The _sensitive_warned set prevents duplicate alerts
        # if the same file is modified multiple times in the same session.
        from tracecode.analysis.scoring import is_sensitive_file
        if is_sensitive_file(rel_path) and rel_path not in self._sensitive_warned:
            self._sensitive_warned.add(rel_path)
            self._write_event("sensitive_file_warned", {"file_path": rel_path})

        # File churn — same file touched more than 5 times.
        # 5 is the threshold because 2-3 touches is normal iterative editing;
        # 6+ touches on the same file in one session usually means the agent
        # is stuck in a loop or repeatedly reverting its own changes.
        count = self._path_counts[rel_path]
        if count > 5 and rel_path not in self._path_churn_warned:
            self._path_churn_warned.add(rel_path)
            self._write_event("file_churn", {"file_path": rel_path, "touch_count": count})

        # Blast radius — more than 15 unique files touched in the last 90 seconds.
        # This fires once per session (not per event) to avoid alert fatigue.
        # 15 files / 90s is a conservative threshold — normal development touches
        # 1-5 files at a time; 15+ in 90s typically means the agent is doing
        # a broad search-and-replace or has lost its scope.
        if not self._blast_radius_fired:
            cutoff = now_ms - 90_000  # 90 seconds ago in milliseconds
            while self._recent_events and self._recent_events[0][0] < cutoff:
                self._recent_events.popleft()
            unique_recent = len({p for _, p in self._recent_events})
            if unique_recent > 15:
                self._blast_radius_fired = True
                self._write_event("blast_radius", {"unique_files": unique_recent, "window_seconds": 90})

    def _write_event(self, event_type: str, payload: dict) -> None:
        try:
            from tracecode.db import get_conn
            with get_conn(self.db_path) as conn:
                conn.execute(
                    "INSERT INTO session_events"
                    " (session_id, event_type, payload, fired_at, notified)"
                    " VALUES (?, ?, ?, ?, 0)",
                    (self.session_id, event_type, json.dumps(payload), int(time.time())),
                )
        except Exception:
            pass

    def _should_ignore(self, abs_path: str) -> bool:
        path = Path(abs_path)
        for part in path.parts:
            if part in IGNORE_DIRS:
                return True
        if path.name in IGNORE_NAMES:
            return True
        if path.suffix.lower() in IGNORE_EXTENSIONS:
            return True
        return False


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_watcher(session_id: str, project_path: str, tracecode_dir: Path) -> None:
    from tracecode.config import DEFAULT_CONFIG_PATH, load_config
    config = load_config(DEFAULT_CONFIG_PATH)
    db_path = config.db_path

    output_path = tracecode_dir / f"watch_{session_id}.jsonl"
    project_path = str(Path(project_path).resolve())
    stop_event = threading.Event()

    def _handle_signal(signum, frame):
        stop_event.set()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    with open(output_path, "a", buffering=1) as output_file:
        handler = FileChangeHandler(
            project_path, output_file, session_id=session_id, db_path=db_path
        )
        observer = Observer()
        observer.schedule(handler, project_path, recursive=True)
        observer.start()
        try:
            stop_event.wait()
        finally:
            observer.stop()
            observer.join(timeout=3)


# ---------------------------------------------------------------------------
# Git-ignore filtering
# ---------------------------------------------------------------------------

def _get_gitignored_paths(paths: list[str], project_path: str) -> frozenset[str]:
    """
    Return the subset of relative paths that git considers ignored.
    Falls back to empty set on any error (non-git repo, git not installed, etc.).
    """
    if not paths:
        return frozenset()
    try:
        result = subprocess.run(
            ["git", "check-ignore", "--stdin"],
            input="\n".join(paths),
            capture_output=True,
            text=True,
            cwd=project_path,
            timeout=5,
        )
        return frozenset(result.stdout.strip().splitlines())
    except Exception:
        return frozenset()


def _is_transient(rel_path: str) -> bool:
    """Return True if the file is a lock file or generated artifact."""
    p = Path(rel_path)
    if p.name in _AGGREGATION_IGNORE_NAMES:
        return True
    # Check compound suffixes like .d.ts, .min.js
    for ext in _AGGREGATION_IGNORE_EXTENSIONS:
        if rel_path.endswith(ext):
            return True
    return False


# ---------------------------------------------------------------------------
# Aggregation — called by session-end after the watcher process is killed
# ---------------------------------------------------------------------------

def aggregate_watch_file(
    session_id: str,
    watch_path: Path,
    conn,
    project_path: str = "",
) -> int:
    """
    Read the JSONL file written by the watcher, aggregate by file path,
    apply gitignore + transient-file filtering, insert rows into file_touches,
    and update sessions.files_touched / hot_files / ignored_touches.

    Returns the number of distinct non-ignored files touched (0 if no data).
    """
    from tracecode.db import bulk_insert_file_touches, update_session

    if not watch_path.exists():
        return 0

    # Parse JSONL
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

    all_paths = list(touches.keys())

    # Apply transient-file filter
    transient = {p for p in all_paths if _is_transient(p)}

    # Apply gitignore filter (only if we know the project path)
    gitignored: frozenset[str] = frozenset()
    if project_path:
        gitignored = _get_gitignored_paths(all_paths, project_path)

    ignored = transient | gitignored
    real_paths = [p for p in all_paths if p not in ignored]

    ignored_count = len(ignored)

    # Insert only real (non-ignored) file touches
    rows = [
        {
            "session_id": session_id,
            "file_path": path,
            "touch_count": touches[path]["count"],
            "first_touch_at": touches[path]["first_ts"],
            "last_touch_at": touches[path]["last_ts"],
        }
        for path in real_paths
    ]
    if rows:
        bulk_insert_file_touches(conn, rows)

    hot_files = sum(1 for p in real_paths if touches[p]["count"] >= 3)
    update_session(conn, session_id,
                   files_touched=len(real_paths),
                   hot_files=hot_files,
                   ignored_touches=ignored_count)

    return len(real_paths)
