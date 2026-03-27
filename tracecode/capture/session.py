"""
capture/session.py — Session lifecycle: start and end.

start_session(): called before claude launches.
  - Creates a session row in the DB.
  - Returns the session UUID (printed to stdout by the CLI so the wrapper can capture it).

end_session(): called after claude exits.
  - Records ended_at and claude_exit_code.
  - Day 2: that's all it does.
  - Days 3–5 will add: watcher aggregation, git analysis, test detection, scoring.

Both functions take an explicit Config so they can be tested with a temp DB.
"""

import time
import uuid
from pathlib import Path

from tracecode.config import Config
from tracecode.db import get_conn, insert_session, update_session


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
    Mark a session as ended.

    Day 2 scope: records ended_at and claude_exit_code only.
    Post-session analysis pipeline (watcher, git, tests, scoring) will be
    wired in here on Days 3–5.
    """
    now = int(time.time())

    with get_conn(config.db_path) as conn:
        update_session(
            conn,
            session_id,
            ended_at=now,
            claude_exit_code=exit_code,
        )
