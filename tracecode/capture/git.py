"""
capture/git.py — Thin wrappers around git CLI commands.

All functions:
  - accept a path (str or Path) to the project directory
  - run git as a subprocess
  - return None / False on any failure — never raise
  - have a short timeout so a slow git never blocks a session

These are read-only queries used at session boundaries (start and end).
Heavier post-session analysis (diffs, commit counting) will be added in Day 4.
"""

import subprocess
from pathlib import Path


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

def _git(args: list[str], cwd: str | Path) -> tuple[int, str]:
    """
    Run `git <args>` in the given directory.
    Returns (exit_code, stdout_stripped).
    Returns (1, "") on timeout or if git is not found.
    """
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode, result.stdout.strip()
    except subprocess.TimeoutExpired:
        return 1, ""
    except (FileNotFoundError, OSError):
        # git not installed or path doesn't exist
        return 1, ""


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------

def is_git_repo(path: str | Path) -> bool:
    """Return True if the path is inside a git repository."""
    code, _ = _git(["rev-parse", "--git-dir"], path)
    return code == 0


def get_branch(path: str | Path) -> str | None:
    """
    Return the current branch name, or None if:
      - not a git repo
      - in detached HEAD state (branch name would be empty)
      - any error
    """
    code, output = _git(["branch", "--show-current"], path)
    if code != 0 or not output:
        return None
    return output


def get_head_sha(path: str | Path) -> str | None:
    """
    Return the full SHA of the current HEAD commit, or None on any failure.
    Returns None on a fresh repo with no commits yet.
    """
    code, output = _git(["rev-parse", "HEAD"], path)
    if code != 0 or not output:
        return None
    return output


def get_project_root(path: str | Path) -> str | None:
    """
    Return the absolute path of the git repo root (top-level directory).
    Returns None if not a git repo.
    Useful for normalising project_path to the repo root rather than a subdirectory.
    """
    code, output = _git(["rev-parse", "--show-toplevel"], path)
    if code != 0 or not output:
        return None
    return output
