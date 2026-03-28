"""
tests/test_git.py — Tests for capture/git.py (is_git_repo, get_branch, get_head_sha, get_project_root)

Fixtures (git_repo, empty_git_repo, plain_dir) come from tests/conftest.py.
"""

import subprocess
from pathlib import Path

import pytest

from tracecode.capture.git import get_branch, get_head_sha, get_project_root, is_git_repo


# ---------------------------------------------------------------------------
# is_git_repo
# ---------------------------------------------------------------------------

class TestIsGitRepo:
    def test_true_for_git_repo(self, git_repo: Path) -> None:
        assert is_git_repo(git_repo) is True

    def test_true_for_subdirectory_of_git_repo(self, git_repo: Path) -> None:
        subdir = git_repo / "src"
        subdir.mkdir()
        assert is_git_repo(subdir) is True

    def test_false_for_plain_directory(self, plain_dir: Path) -> None:
        assert is_git_repo(plain_dir) is False

    def test_false_for_nonexistent_path(self, tmp_path: Path) -> None:
        assert is_git_repo(tmp_path / "does_not_exist") is False

    def test_accepts_string_path(self, git_repo: Path) -> None:
        assert is_git_repo(str(git_repo)) is True


# ---------------------------------------------------------------------------
# get_branch
# ---------------------------------------------------------------------------

class TestGetBranch:
    def test_returns_branch_name(self, git_repo: Path) -> None:
        branch = get_branch(git_repo)
        # git init creates 'main' or 'master' depending on git config
        assert branch in ("main", "master")

    def test_returns_none_for_plain_dir(self, plain_dir: Path) -> None:
        assert get_branch(plain_dir) is None

    def test_returns_none_for_nonexistent_path(self, tmp_path: Path) -> None:
        assert get_branch(tmp_path / "does_not_exist") is None

    def test_returns_custom_branch_name(self, git_repo: Path) -> None:
        subprocess.run(
            ["git", "-C", str(git_repo), "checkout", "-b", "feature/auth"],
            check=True, capture_output=True,
        )
        assert get_branch(git_repo) == "feature/auth"

    def test_returns_branch_name_for_empty_repo(self, empty_git_repo: Path) -> None:
        # Modern git (2.28+) returns the intended branch name even before the first commit.
        # The branch name is valid; there's just no commit yet.
        result = get_branch(empty_git_repo)
        # Returns the default branch name ("main" or "master") or None — never raises.
        assert result is None or isinstance(result, str)


# ---------------------------------------------------------------------------
# get_head_sha
# ---------------------------------------------------------------------------

class TestGetHeadSha:
    def test_returns_40_char_sha(self, git_repo: Path) -> None:
        sha = get_head_sha(git_repo)
        assert sha is not None
        assert len(sha) == 40
        assert all(c in "0123456789abcdef" for c in sha)

    def test_returns_none_for_plain_dir(self, plain_dir: Path) -> None:
        assert get_head_sha(plain_dir) is None

    def test_returns_none_for_empty_repo(self, empty_git_repo: Path) -> None:
        # No commits → HEAD does not point to a valid commit
        assert get_head_sha(empty_git_repo) is None

    def test_sha_changes_after_new_commit(self, git_repo: Path) -> None:
        sha_before = get_head_sha(git_repo)

        (git_repo / "newfile.txt").write_text("new")
        subprocess.run(["git", "-C", str(git_repo), "add", "."], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(git_repo), "commit", "-m", "second commit"],
            check=True, capture_output=True,
        )

        sha_after = get_head_sha(git_repo)
        assert sha_before != sha_after

    def test_accepts_string_path(self, git_repo: Path) -> None:
        sha = get_head_sha(str(git_repo))
        assert sha is not None


# ---------------------------------------------------------------------------
# get_project_root
# ---------------------------------------------------------------------------

class TestGetProjectRoot:
    def test_returns_repo_root_from_root(self, git_repo: Path) -> None:
        root = get_project_root(git_repo)
        assert root == str(git_repo)

    def test_returns_repo_root_from_subdirectory(self, git_repo: Path) -> None:
        subdir = git_repo / "deep" / "nested"
        subdir.mkdir(parents=True)
        root = get_project_root(subdir)
        assert root == str(git_repo)

    def test_returns_none_for_plain_dir(self, plain_dir: Path) -> None:
        assert get_project_root(plain_dir) is None
