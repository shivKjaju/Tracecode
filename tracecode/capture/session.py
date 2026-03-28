"""
capture/session.py — Session lifecycle: start and end.

start_session(): called before claude launches.
  - Creates a session row in the DB.
  - Returns the session UUID (printed to stdout by the CLI so the wrapper can capture it).

end_session(): called after claude exits.
  - Day 2: records ended_at and claude_exit_code.
  - Day 3: kills the watcher subprocess, aggregates file touch data.
  - Days 4–5 will add: git analysis, test detection, scoring.

Both functions take an explicit Config so they can be tested with a temp DB.
"""

import logging
import os
import signal
import time
import uuid
from pathlib import Path

from tracecode.config import Config
from tracecode.db import get_conn, insert_session, update_session

logger = logging.getLogger(__name__)


def start_session(
    project_path: str | Path,
    git_branch: str | None,
    git_commit: str | None,
    config: Config,
) -> str:
    """
    Create a new session row and return the session UUID.

    Resolves project_path to its absolute form so it is stable regardless
    of the working directory when the wrapper is invoked.
    """
    project_path = Path(project_path).resolve()

    session_id = str(uuid.uuid4())
    now = int(time.time())

    session = {
        "id": session_id,
        "started_at": now,
        "project_path": str(project_path),
        "project_name": project_path.name,
        "git_branch": git_branch or None,
        "git_commit_before": git_commit or None,
    }

    with get_conn(config.db_path) as conn:
        insert_session(conn, session)

    return session_id


def end_session(
    session_id: str,
    exit_code: int,
    config: Config,
) -> None:
    """
    Mark a session as ended and run the post-session analysis pipeline.

    Steps run in order — each step is wrapped in its own try/except so a
    failure in one step never prevents the remaining steps from running.
    A broken post-session hook must never surface as an error to the developer.
    """
    # Step 1: Record ended_at and exit code immediately
    now = int(time.time())
    with get_conn(config.db_path) as conn:
        update_session(conn, session_id, ended_at=now, claude_exit_code=exit_code)

    # Step 2: Kill the watcher subprocess
    try:
        _kill_watcher(session_id, config)
    except Exception as exc:
        logger.warning("Failed to kill watcher for session %s: %s", session_id, exc)

    # Step 3: Aggregate watcher JSONL into file_touches table
    try:
        watch_path = config.tracecode_dir / f"watch_{session_id}.jsonl"
        from tracecode.capture.watcher import aggregate_watch_file
        with get_conn(config.db_path) as conn:
            aggregate_watch_file(session_id, watch_path, conn)
        # Clean up the temp file
        watch_path.unlink(missing_ok=True)
    except Exception as exc:
        logger.warning("Failed to aggregate watch file for session %s: %s", session_id, exc)

    # Steps 4–5 (Days 4–5): git analysis, test detection, scoring


def _kill_watcher(session_id: str, config: Config) -> None:
    """
    Send SIGTERM to the watcher subprocess and clean up its PID file.
    Silent if the process is already gone.
    """
    pid_file = config.tracecode_dir / f"watcher_{session_id}.pid"
    if not pid_file.exists():
        return

    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, signal.SIGTERM)
        # Give the watcher a moment to flush its output file before we read it
        time.sleep(0.3)
    except ProcessLookupError:
        pass  # process already exited — fine
    except (ValueError, OSError) as exc:
        logger.warning("Could not kill watcher PID for session %s: %s", session_id, exc)
    finally:
        pid_file.unlink(missing_ok=True)
