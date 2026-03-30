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

import re
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


def get_commits_since(path: str | Path, start_sha: str | None) -> int:
    """
    Count commits added to HEAD since start_sha.
    Returns 0 if start_sha is None, invalid, or if git fails.

    Uses `git rev-list --count <start_sha>..HEAD` which is reliable and fast.
    If start_sha == HEAD (no new commits), returns 0 correctly.
    """
    if not start_sha:
        return 0
    code, output = _git(["rev-list", "--count", f"{start_sha}..HEAD"], path)
    if code != 0 or not output:
        return 0
    try:
        return int(output)
    except ValueError:
        return 0


def is_tree_dirty(path: str | Path) -> bool:
    """
    Return True if there are any uncommitted changes in the working tree.
    Includes: modified tracked files, staged changes, untracked files.
    Returns False if not a git repo or git fails.
    """
    code, output = _git(["status", "--porcelain"], path)
    if code != 0:
        return False
    return bool(output.strip())


def get_dirty_files(path: str | Path) -> list[str]:
    """
    Return relative paths of files with uncommitted changes (modified or staged).
    Handles renamed files — returns the new name.
    Returns [] if the tree is clean or git fails.

    NOTE: does not use _git() because _git() strips the full stdout, which
    corrupts the fixed-column porcelain format when there is only one dirty
    file (the leading status character gets stripped off).
    """
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(path),
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return []

    if result.returncode != 0:
        return []

    files = []
    for line in result.stdout.splitlines():
        # Porcelain v1 format: XY<space>filename  (XY = 2-char status code)
        if len(line) < 3:
            continue
        filename = line[3:].strip()
        # Renamed files: "old -> new"
        if " -> " in filename:
            filename = filename.split(" -> ", 1)[1]
        if filename:
            files.append(filename)
    return files


def get_net_changed_files(path: str | Path, start_sha: str | None) -> list[str]:
    """
    Return relative paths of files that changed between start_sha and the
    current working tree (includes staged and unstaged changes).

    Used for persistence rate calculation: a file is "persisted" if it
    appears in this list.

    Returns [] if start_sha is None, the tree is unchanged, or git fails.
    """
    if not start_sha:
        return []
    code, output = _git(["diff", "--name-only", start_sha], path)
    if code != 0 or not output:
        return []
    return [f.strip() for f in output.splitlines() if f.strip()]


def get_net_diff(path: str | Path, start_sha: str | None) -> str | None:
    """
    Return the unified diff of all changes since start_sha, including
    staged and unstaged changes in the working tree.

    Called on-demand by the API (GET /api/sessions/:id/diff).
    NOT called during session-end — too expensive to run on every session.

    Returns None if start_sha is None, no changes, or git fails.
    """
    if not start_sha:
        return None
    code, output = _git(["diff", start_sha], path)
    if code != 0:
        return None
    return output if output.strip() else None


def count_diff_lines(path: str | Path, start_sha: str | None) -> int | None:
    """
    Return the total lines changed (added + removed) between start_sha and HEAD.
    Uses `git diff --stat` which is fast and does not output file contents.
    Returns None if start_sha is absent, the repo has no changes, or git fails.
    """
    if not start_sha:
        return None
    code, output = _git(["diff", "--stat", start_sha, "HEAD"], path)
    if code != 0 or not output:
        return None
    # Last line of --stat: "N files changed, X insertions(+), Y deletions(-)"
    last = output.strip().splitlines()[-1]
    added_m   = re.search(r'(\d+) insertion', last)
    removed_m = re.search(r'(\d+) deletion', last)
    added   = int(added_m.group(1))   if added_m   else 0
    removed = int(removed_m.group(1)) if removed_m else 0
    total = added + removed
    return total if total > 0 else None


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
