"""
analysis/persistence.py — Persistence rate calculation.

Persistence rate answers: "Of the files the agent touched during this session,
how many actually survived in git state at the end?"

A file "persisted" if it shows a net change from start_sha to the current
working tree (committed, staged, or still modified). A file "did not persist"
if it was touched by the watcher but shows no net diff — meaning the changes
were reverted before the session ended.

This is an approximation, not ground truth. Edge cases that make it wrong:
  - A file touched, reverted, then re-edited to be identical to the start
  - Binary files
  - Files moved or renamed mid-session

The is_reliable flag is False whenever we can't trust the result. The UI
shows "(~approx)" and the score calculation skips this signal when unreliable.
"""

from pathlib import Path

from tracecode.capture.git import (
    get_dirty_files,
    get_net_changed_files,
    is_git_repo,
)
from tracecode.db import get_file_touches, update_file_touch_persisted


def compute_persistence(
    session_id: str,
    project_path: str | Path,
    start_sha: str | None,
    conn,
) -> tuple[float | None, bool]:
    """
    Calculate the persistence rate for a session.

    Returns:
        (persistence_rate, is_reliable)

        persistence_rate: float 0.0–1.0, or None if not computable
        is_reliable:      True if the calculation is trustworthy

    Also updates the persisted column on each file_touch row as a side effect.
    """
    project_path = str(Path(project_path).resolve())

    # Can't compute without git or a start reference point
    if not is_git_repo(project_path) or not start_sha:
        return None, False

    touches = get_file_touches(conn, session_id)
    if not touches:
        # No files were touched — nothing to measure
        return None, False

    try:
        # Files with a net change from start_sha to current working tree.
        # This covers: committed changes, staged changes, unstaged modifications.
        net_changed = set(get_net_changed_files(project_path, start_sha))

        # Also include files that are dirty (modified but not in the diff above,
        # e.g. newly untracked files the watcher caught)
        dirty = set(get_dirty_files(project_path))

        surviving = net_changed | dirty

        persisted_count = 0
        for touch in touches:
            file_persisted = touch["file_path"] in surviving
            if touch["id"] is not None:
                update_file_touch_persisted(conn, touch["id"], file_persisted)
            if file_persisted:
                persisted_count += 1

        rate = persisted_count / len(touches)
        return round(rate, 3), True

    except Exception:
        # Any git failure → unreliable, don't include in score
        return None, False
