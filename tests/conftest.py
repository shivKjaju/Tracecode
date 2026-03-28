"""
tests/conftest.py — Shared pytest fixtures available to all test files.
"""

import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """
    A git repo with one initial commit.
    Returns the repo root path.
    """
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "test@example.com"],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.name", "Test User"],
        check=True, capture_output=True,
    )
    (tmp_path / "README.md").write_text("# test project")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-m", "init"],
        check=True, capture_output=True,
    )
    return tmp_path


@pytest.fixture
def empty_git_repo(tmp_path: Path) -> Path:
    """A git repo with no commits yet (HEAD does not exist)."""
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    return tmp_path


@pytest.fixture
def plain_dir(tmp_path: Path) -> Path:
    """A plain directory with no git repo."""
    (tmp_path / "somefile.txt").write_text("hello")
    return tmp_path
