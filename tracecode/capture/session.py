"""
capture/session.py — Session lifecycle: start and end.

start_session(): called before claude launches.
  - Creates a session row in the DB.
  - Returns the session UUID printed to stdout so the wrapper can capture it.

end_session(): called after claude exits.
  Runs the full post-session analysis pipeline in order:
    1. Record ended_at + exit code
    2. Kill watcher subprocess
    3. Aggregate file touches (watcher JSONL → file_touches table)
    4. Git analysis (commits, dirty state, commit SHA)
    5. Persistence rate
    6. Test detection
    7. Scoring (wandering, outcome, quality, auto_outcome)

Each step is wrapped in its own try/except. A failure in any step is logged
and skipped — it never prevents later steps from running and never surfaces
as an error to the developer after their claude session ends.
"""

import logging
import os
import signal
import time
import uuid
from pathlib import Path

from tracecode.config import Config
from tracecode.db import get_conn, get_session, insert_session, update_session

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# start_session
# ---------------------------------------------------------------------------

def start_session(
    project_path: str | Path,
    git_branch: str | None,
    git_commit: str | None,
    config: Config,
) -> str:
    """
    Insert a new session row and return the UUID.
    Resolves project_path to absolute so it is stable regardless of cwd.
    """
    project_path = Path(project_path).resolve()
    session_id = str(uuid.uuid4())
    now = int(time.time())

    with get_conn(config.db_path) as conn:
        insert_session(conn, {
            "id":               session_id,
            "started_at":       now,
            "project_path":     str(project_path),
            "project_name":     project_path.name,
            "git_branch":       git_branch or None,
            "git_commit_before": git_commit or None,
        })

    return session_id


# ---------------------------------------------------------------------------
# end_session
# ---------------------------------------------------------------------------

def end_session(
    session_id: str,
    exit_code: int,
    config: Config,
    project_path: str | None = None,
    git_commit_before: str | None = None,
) -> None:
    """
    Mark the session as ended and run all post-session analysis steps.

    project_path and git_commit_before may be passed by the CLI (from the
    wrapper's environment) or read back from the DB row if not supplied.
    """

    # ------------------------------------------------------------------
    # Step 1: Record ended_at immediately — most important update
    # ------------------------------------------------------------------
    now = int(time.time())
    with get_conn(config.db_path) as conn:
        update_session(conn, session_id, ended_at=now, claude_exit_code=exit_code)

    # ------------------------------------------------------------------
    # Read full session row — resolve any missing caller arguments
    # and get started_at for test artifact freshness checks.
    # ------------------------------------------------------------------
    session_row: dict = {}
    started_at: int = now  # fallback if DB read fails
    try:
        with get_conn(config.db_path) as conn:
            session_row = get_session(conn, session_id) or {}
        project_path     = project_path     or session_row.get("project_path")     or ""
        git_commit_before = git_commit_before or session_row.get("git_commit_before") or ""
        started_at       = int(session_row.get("started_at") or now)
    except Exception as exc:
        logger.warning("Could not read session row for %s: %s", session_id, exc)
        project_path      = project_path or ""
        git_commit_before = git_commit_before or ""

    # ------------------------------------------------------------------
    # Step 2: Kill the watcher subprocess
    # ------------------------------------------------------------------
    try:
        _kill_watcher(session_id, config)
    except Exception as exc:
        logger.warning("Failed to kill watcher for %s: %s", session_id, exc)

    # ------------------------------------------------------------------
    # Step 3: Aggregate watcher JSONL → file_touches table
    # ------------------------------------------------------------------
    try:
        from tracecode.capture.watcher import aggregate_watch_file
        watch_path = config.tracecode_dir / f"watch_{session_id}.jsonl"
        with get_conn(config.db_path) as conn:
            aggregate_watch_file(session_id, watch_path, conn,
                                 project_path=project_path)
        watch_path.unlink(missing_ok=True)
    except Exception as exc:
        logger.warning("Watcher aggregation failed for %s: %s", session_id, exc)

    # ------------------------------------------------------------------
    # Step 3.5: Detect sensitive files from aggregated touches
    # ------------------------------------------------------------------
    try:
        from tracecode.db import get_file_touches
        from tracecode.analysis.scoring import is_sensitive_file
        with get_conn(config.db_path) as conn:
            touches = get_file_touches(conn, session_id)
        sensitive = any(is_sensitive_file(t["file_path"]) for t in touches)
        with get_conn(config.db_path) as conn:
            update_session(conn, session_id, sensitive_files_touched=1 if sensitive else 0)
    except Exception as exc:
        logger.warning("Sensitive file detection failed for %s: %s", session_id, exc)

    # ------------------------------------------------------------------
    # Step 4: Git analysis
    # ------------------------------------------------------------------
    try:
        from tracecode.capture.git import (
            count_diff_lines,
            get_commits_since,
            get_head_sha,
            is_git_repo,
            is_tree_dirty,
        )
        if project_path and is_git_repo(project_path):
            diff_lines = count_diff_lines(project_path, git_commit_before or None)
            with get_conn(config.db_path) as conn:
                update_session(conn, session_id,
                    git_commit_after = get_head_sha(project_path),
                    commits_during   = get_commits_since(project_path, git_commit_before or None),
                    tree_dirty       = 1 if is_tree_dirty(project_path) else 0,
                    diff_lines       = diff_lines,
                )
    except Exception as exc:
        logger.warning("Git analysis failed for %s: %s", session_id, exc)

    # ------------------------------------------------------------------
    # Step 5: Persistence rate
    # ------------------------------------------------------------------
    try:
        from tracecode.analysis.persistence import compute_persistence
        with get_conn(config.db_path) as conn:
            rate, reliable = compute_persistence(
                session_id, project_path, git_commit_before or None, conn
            )
            update_session(conn, session_id,
                persistence_rate     = rate,
                persistence_reliable = 1 if reliable else 0,
            )
    except Exception as exc:
        logger.warning("Persistence calculation failed for %s: %s", session_id, exc)

    # ------------------------------------------------------------------
    # Step 6: Test detection
    # ------------------------------------------------------------------
    try:
        from tracecode.analysis.tests import detect_test_outcome
        outcome, source = detect_test_outcome(project_path, started_at, config)
        if outcome is not None:
            with get_conn(config.db_path) as conn:
                update_session(conn, session_id,
                    test_outcome = outcome,
                    test_source  = source,
                )
    except Exception as exc:
        logger.warning("Test detection failed for %s: %s", session_id, exc)

    # ------------------------------------------------------------------
    # Step 7: Scoring — reads the fully-populated row, writes all scores
    # ------------------------------------------------------------------
    try:
        from tracecode.analysis.scoring import compute_all
        with get_conn(config.db_path) as conn:
            final_row = get_session(conn, session_id) or {}
            if final_row:
                scores = compute_all(final_row)
                update_session(conn, session_id, **scores)
    except Exception as exc:
        logger.warning("Scoring failed for %s: %s", session_id, exc)

    # ------------------------------------------------------------------
    # Step 8: Verdict — requires file touches + risky commands
    # ------------------------------------------------------------------
    try:
        from tracecode.analysis.scoring import compute_anomalies, compute_verdict
        from tracecode.db import get_file_touches, get_risky_commands, count_risky_commands
        with get_conn(config.db_path) as conn:
            final_row   = get_session(conn, session_id) or {}
            touches     = get_file_touches(conn, session_id)
            risks       = get_risky_commands(conn, session_id)
            risk_counts = count_risky_commands(conn, session_id)
        if final_row:
            anomalies = compute_anomalies(final_row, touches, risks)
            verdict   = compute_verdict(
                risk_counts["catastrophic"],
                risk_counts["risky"],
                anomalies,
            )
            with get_conn(config.db_path) as conn:
                update_session(conn, session_id, verdict=verdict)
    except Exception as exc:
        logger.warning("Verdict computation failed for %s: %s", session_id, exc)


# ---------------------------------------------------------------------------
# Internal: watcher lifecycle
# ---------------------------------------------------------------------------

def _kill_watcher(session_id: str, config: Config) -> None:
    """Send SIGTERM to the watcher subprocess and remove its PID file."""
    pid_file = config.tracecode_dir / f"watcher_{session_id}.pid"
    if not pid_file.exists():
        return
    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, signal.SIGTERM)
        time.sleep(0.3)   # let the watcher flush before we read its output
    except ProcessLookupError:
        pass              # already exited — fine
    except (ValueError, OSError) as exc:
        logger.warning("Could not kill watcher PID for %s: %s", session_id, exc)
    finally:
        pid_file.unlink(missing_ok=True)
