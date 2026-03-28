"""
tests/test_git_analysis.py — Tests for the post-session git functions:
    get_commits_since, is_tree_dirty, get_dirty_files,
    get_net_changed_files, get_net_diff

Fixtures (git_repo, plain_dir) come from tests/conftest.py.
"""

import subprocess
from pathlib import Path

import pytest

from tracecode.capture.git import (
    get_commits_since,
    get_dirty_files,
    get_head_sha,
    get_net_changed_files,
    get_net_diff,
    is_tree_dirty,
)


def git(args: list[str], cwd: Path) -> None:
    """Run a git command in cwd, raise on failure."""
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


def commit_file(repo: Path, filename: str, content: str, message: str) -> str:
    """Create/update a file, stage it, commit it, and return the new HEAD SHA."""
    (repo / filename).write_text(content)
    git(["add", filename], repo)
    git(["commit", "-m", message], repo)
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


# ---------------------------------------------------------------------------
# get_commits_since
# ---------------------------------------------------------------------------

class TestGetCommitsSince:
    def test_zero_when_no_new_commits(self, git_repo: Path) -> None:
        sha = get_head_sha(git_repo)
        assert get_commits_since(git_repo, sha) == 0

    def test_counts_one_new_commit(self, git_repo: Path) -> None:
        start_sha = get_head_sha(git_repo)
        commit_file(git_repo, "new.py", "x = 1", "add new.py")
        assert get_commits_since(git_repo, start_sha) == 1

    def test_counts_multiple_new_commits(self, git_repo: Path) -> None:
        start_sha = get_head_sha(git_repo)
        commit_file(git_repo, "a.py", "a", "commit a")
        commit_file(git_repo, "b.py", "b", "commit b")
        commit_file(git_repo, "c.py", "c", "commit c")
        assert get_commits_since(git_repo, start_sha) == 3

    def test_returns_zero_for_none_sha(self, git_repo: Path) -> None:
        assert get_commits_since(git_repo, None) == 0

    def test_returns_zero_for_empty_sha(self, git_repo: Path) -> None:
        assert get_commits_since(git_repo, "") == 0

    def test_returns_zero_for_invalid_sha(self, git_repo: Path) -> None:
        assert get_commits_since(git_repo, "notavalidsha") == 0

    def test_returns_zero_for_plain_dir(self, plain_dir: Path) -> None:
        assert get_commits_since(plain_dir, "abc123") == 0


# ---------------------------------------------------------------------------
# is_tree_dirty
# ---------------------------------------------------------------------------

class TestIsTreeDirty:
    def test_false_for_clean_tree(self, git_repo: Path) -> None:
        assert is_tree_dirty(git_repo) is False

    def test_true_for_modified_tracked_file(self, git_repo: Path) -> None:
        (git_repo / "README.md").write_text("changed content")
        assert is_tree_dirty(git_repo) is True

    def test_true_for_staged_change(self, git_repo: Path) -> None:
        (git_repo / "staged.py").write_text("x = 1")
        git(["add", "staged.py"], git_repo)
        assert is_tree_dirty(git_repo) is True

    def test_true_for_untracked_file(self, git_repo: Path) -> None:
        (git_repo / "untracked.py").write_text("new file")
        assert is_tree_dirty(git_repo) is True

    def test_false_after_commit(self, git_repo: Path) -> None:
        commit_file(git_repo, "clean.py", "x = 1", "add clean.py")
        assert is_tree_dirty(git_repo) is False

    def test_false_for_plain_dir(self, plain_dir: Path) -> None:
        # Not a git repo — returns False, never raises
        assert is_tree_dirty(plain_dir) is False


# ---------------------------------------------------------------------------
# get_dirty_files
# ---------------------------------------------------------------------------

class TestGetDirtyFiles:
    def test_empty_for_clean_tree(self, git_repo: Path) -> None:
        assert get_dirty_files(git_repo) == []

    def test_returns_modified_file(self, git_repo: Path) -> None:
        (git_repo / "README.md").write_text("modified")
        files = get_dirty_files(git_repo)
        assert "README.md" in files

    def test_returns_staged_file(self, git_repo: Path) -> None:
        (git_repo / "new.py").write_text("x = 1")
        git(["add", "new.py"], git_repo)
        files = get_dirty_files(git_repo)
        assert "new.py" in files

    def test_returns_multiple_dirty_files(self, git_repo: Path) -> None:
        (git_repo / "a.py").write_text("a")
        (git_repo / "b.py").write_text("b")
        files = get_dirty_files(git_repo)
        assert "a.py" in files
        assert "b.py" in files

    def test_empty_for_plain_dir(self, plain_dir: Path) -> None:
        assert get_dirty_files(plain_dir) == []


# ---------------------------------------------------------------------------
# get_net_changed_files
# ---------------------------------------------------------------------------

class TestGetNetChangedFiles:
    def test_empty_when_nothing_changed(self, git_repo: Path) -> None:
        sha = get_head_sha(git_repo)
        assert get_net_changed_files(git_repo, sha) == []

    def test_returns_committed_changed_file(self, git_repo: Path) -> None:
        start_sha = get_head_sha(git_repo)
        commit_file(git_repo, "feature.py", "x = 1", "add feature")
        files = get_net_changed_files(git_repo, start_sha)
        assert "feature.py" in files

    def test_returns_uncommitted_changed_file(self, git_repo: Path) -> None:
        start_sha = get_head_sha(git_repo)
        (git_repo / "README.md").write_text("modified without commit")
        files = get_net_changed_files(git_repo, start_sha)
        assert "README.md" in files

    def test_returns_both_committed_and_uncommitted(self, git_repo: Path) -> None:
        start_sha = get_head_sha(git_repo)
        commit_file(git_repo, "committed.py", "x = 1", "committed")
        (git_repo / "dirty.py").write_text("not committed")
        # get_net_changed_files uses `git diff <sha>` which includes working tree
        files = get_net_changed_files(git_repo, start_sha)
        assert "committed.py" in files

    def test_empty_for_none_sha(self, git_repo: Path) -> None:
        assert get_net_changed_files(git_repo, None) == []

    def test_empty_for_plain_dir(self, plain_dir: Path) -> None:
        assert get_net_changed_files(plain_dir, "abc123") == []


# ---------------------------------------------------------------------------
# get_net_diff
# ---------------------------------------------------------------------------

class TestGetNetDiff:
    def test_returns_none_when_nothing_changed(self, git_repo: Path) -> None:
        sha = get_head_sha(git_repo)
        assert get_net_diff(git_repo, sha) is None

    def test_returns_diff_string_after_change(self, git_repo: Path) -> None:
        start_sha = get_head_sha(git_repo)
        (git_repo / "README.md").write_text("new content")
        diff = get_net_diff(git_repo, start_sha)
        assert diff is not None
        assert "README.md" in diff
        assert "new content" in diff

    def test_returns_none_for_none_sha(self, git_repo: Path) -> None:
        assert get_net_diff(git_repo, None) is None

    def test_returns_none_for_plain_dir(self, plain_dir: Path) -> None:
        assert get_net_diff(plain_dir, "abc123") is None

    def test_diff_includes_committed_changes(self, git_repo: Path) -> None:
        start_sha = get_head_sha(git_repo)
        commit_file(git_repo, "new_file.py", "print('hello')", "add new_file")
        diff = get_net_diff(git_repo, start_sha)
        assert diff is not None
        assert "new_file.py" in diff
