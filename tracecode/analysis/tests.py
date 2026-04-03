"""
analysis/tests.py — Test outcome detection pipeline.

Priority order (per V1 spec):
  1. Configured test_command in config.toml  → run it, use exit code
  2. Known artifact files left by test runner → parse result
  3. Skip                                    → return (None, None)

Artifacts checked (in order):
  - pytest: .pytest_cache/v/cache/lastfailed  (mtime within session window)
  - JUnit XML: common locations               (mtime within session window)

A stale artifact (mtime < session_start) is always ignored.
Any failure in this module is swallowed by the caller — never surfaces to the user.
"""

import json
import shlex
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

from tracecode.config import Config


def detect_test_outcome(
    project_path: str | Path,
    session_start: int,
    config: Config,
) -> tuple[str | None, str | None]:
    """
    Run the test detection pipeline.

    Returns:
        (outcome, source)
        outcome: 'pass' | 'fail' | None
        source:  'config' | 'artifact' | None
    """
    project_path = Path(project_path).resolve()

    # Priority 1: configured command
    cmd = config.get_test_command(str(project_path))
    if cmd:
        timeout = config.get_test_timeout(str(project_path))
        exit_code = _run_command(cmd, project_path, timeout)
        if exit_code is not None:
            return ("pass" if exit_code == 0 else "fail"), "config"

    # Priority 2: artifact detection
    outcome = _detect_from_artifacts(project_path, session_start)
    if outcome is not None:
        return outcome, "artifact"

    # Priority 3: skip
    return None, None


# ---------------------------------------------------------------------------
# Command runner
# ---------------------------------------------------------------------------

def _run_command(cmd: str, cwd: Path, timeout: int) -> int | None:
    """
    Run a test command and return its exit code.
    Returns None on timeout or if the command is not found.
    Uses shlex.split so 'pytest -q --tb=no' works correctly.
    Never raises.
    """
    try:
        result = subprocess.run(
            shlex.split(cmd),
            cwd=str(cwd),
            capture_output=True,    # don't pollute the terminal
            timeout=timeout,
        )
        return result.returncode
    except subprocess.TimeoutExpired:
        return None
    except (FileNotFoundError, OSError):
        # Command not found (e.g. pytest not installed in this project)
        return None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Artifact detection
# ---------------------------------------------------------------------------

def _detect_from_artifacts(project_path: Path, session_start: int) -> str | None:
    """
    Check for test result artifacts written during the session.
    Returns 'pass', 'fail', or None.
    """
    outcome = _check_pytest_cache(project_path, session_start)
    if outcome is not None:
        return outcome

    outcome = _check_jest_vitest_json(project_path, session_start)
    if outcome is not None:
        return outcome

    outcome = _check_junit_xml(project_path, session_start)
    if outcome is not None:
        return outcome

    return None


def _is_fresh(path: Path, session_start: int) -> bool:
    """Return True if the file was modified during or after session_start."""
    try:
        return int(path.stat().st_mtime) >= session_start
    except OSError:
        return False


def _check_pytest_cache(project_path: Path, session_start: int) -> str | None:
    """
    Inspect .pytest_cache/v/cache/lastfailed.

    pytest writes this file after every run:
      - Empty dict {}    → all tests passed (no failures to remember)
      - Non-empty dict   → maps test IDs to True for each failed test

    We only trust it if the mtime is >= session_start (written this session).
    """
    cache_file = project_path / ".pytest_cache" / "v" / "cache" / "lastfailed"
    if not cache_file.exists() or not _is_fresh(cache_file, session_start):
        return None

    try:
        content = cache_file.read_text().strip()
        if not content:
            return "pass"
        data = json.loads(content)
        if not isinstance(data, dict):
            return None
        return "fail" if data else "pass"
    except (json.JSONDecodeError, OSError):
        return None


def _check_jest_vitest_json(project_path: Path, session_start: int) -> str | None:
    """
    Check for JSON output files written by jest or vitest.

    Both runners write the same JSON shape when configured to do so:
      jest:   jest --json --outputFile=jest-results.json
      vitest: vitest run --reporter=json --outputFile=vitest-results.json

    JSON shape (either runner):
      { "success": true/false, "numFailedTests": N, "numTotalTests": N, ... }

    We try "success" first (definitive boolean), then fall back to
    "numFailedTests" in case the field is present but "success" is not.
    """
    candidates = [
        project_path / "jest-results.json",
        project_path / "vitest-results.json",
        project_path / ".jest-results.json",
        project_path / "test-results.json",
        project_path / "reports" / "test-results.json",
    ]

    for candidate in candidates:
        if not candidate.exists() or not _is_fresh(candidate, session_start):
            continue
        try:
            data = json.loads(candidate.read_text())
            if not isinstance(data, dict):
                continue
            # "success" field is set by both jest --json and vitest --reporter=json
            if "success" in data:
                return "pass" if data["success"] else "fail"
            # Fallback: count failed tests directly
            if "numFailedTests" in data:
                return "fail" if data["numFailedTests"] > 0 else "pass"
        except (json.JSONDecodeError, OSError, TypeError):
            continue

    return None


def _check_junit_xml(project_path: Path, session_start: int) -> str | None:
    """
    Check common JUnit XML output locations.
    Parses the testsuite 'failures' and 'errors' attributes.

    Covers: pytest (pytest-junit), jest (jest-junit package),
    vitest (--reporter=junit), Maven/Gradle (target/surefire-reports),
    and Rust nextest.
    """
    candidates = [
        project_path / "junit.xml",
        project_path / "test-results.xml",
        project_path / "test-report.xml",
        project_path / "test-results" / "junit.xml",
        project_path / "reports" / "junit.xml",
        project_path / "reports" / "jest" / "junit.xml",
        project_path / "target" / "nextest" / "ci" / "junit.xml",
        project_path / "coverage" / "junit.xml",
    ]

    for candidate in candidates:
        if not candidate.exists() or not _is_fresh(candidate, session_start):
            continue
        try:
            root = ET.parse(candidate).getroot()
            # Handle both <testsuite> and <testsuites><testsuite>
            suite = root if root.tag == "testsuite" else root.find("testsuite")
            if suite is None:
                continue
            failures = int(suite.get("failures", 0))
            errors   = int(suite.get("errors", 0))
            return "fail" if (failures > 0 or errors > 0) else "pass"
        except (ET.ParseError, ValueError, OSError):
            continue

    return None
