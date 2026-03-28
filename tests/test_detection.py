"""
tests/test_detection.py — Tests for analysis/tests.py

Tests cover:
  1. Priority 1: configured test command (real subprocess)
  2. Priority 2: artifact detection (pytest cache, JUnit XML)
  3. Priority 3: skip when no signals available
  4. Stale artifact rejection
"""

import json
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from tracecode.analysis.tests import (
    _check_junit_xml,
    _check_pytest_cache,
    _run_command,
    detect_test_outcome,
)
from tracecode.config import Config, DEFAULT_IGNORE_DIRS, DEFAULT_IGNORE_EXTENSIONS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SESSION_START = int(time.time()) - 60   # 1 minute ago


def make_config(test_command: str | None = None) -> Config:
    return Config(
        db_path=Path("/tmp/test.db"),   # not used in these tests
        server_port=7842,
        claude_binary="",
        log_file=Path("/tmp/test.log"),
        test_command=test_command,
        test_timeout=10,
        watch_ignore_dirs=DEFAULT_IGNORE_DIRS,
        watch_ignore_extensions=DEFAULT_IGNORE_EXTENSIONS,
    )


def write_pytest_cache(project: Path, failures: dict, mtime_offset: int = 10) -> Path:
    """Write a .pytest_cache/v/cache/lastfailed file and set its mtime."""
    cache_dir = project / ".pytest_cache" / "v" / "cache"
    cache_dir.mkdir(parents=True)
    f = cache_dir / "lastfailed"
    f.write_text(json.dumps(failures))
    # Set mtime to now + offset so it's fresh relative to SESSION_START
    ts = SESSION_START + mtime_offset
    import os
    os.utime(f, (ts, ts))
    return f


def write_junit_xml(path: Path, failures: int = 0, errors: int = 0) -> Path:
    """Write a minimal JUnit XML file at path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    root = ET.Element("testsuite", {
        "name": "tests",
        "tests": str(failures + errors + 1),
        "failures": str(failures),
        "errors": str(errors),
    })
    path.write_text(ET.tostring(root, encoding="unicode"))
    ts = SESSION_START + 10
    import os
    os.utime(path, (ts, ts))
    return path


# ---------------------------------------------------------------------------
# _run_command
# ---------------------------------------------------------------------------

class TestRunCommand:
    def test_returns_zero_for_passing_command(self, tmp_path: Path) -> None:
        result = _run_command("python3 -c 'import sys; sys.exit(0)'", tmp_path, 10)
        assert result == 0

    def test_returns_nonzero_for_failing_command(self, tmp_path: Path) -> None:
        result = _run_command("python3 -c 'import sys; sys.exit(1)'", tmp_path, 10)
        assert result == 1

    def test_returns_none_for_missing_command(self, tmp_path: Path) -> None:
        result = _run_command("nonexistent_command_xyz --version", tmp_path, 10)
        assert result is None

    def test_returns_none_on_timeout(self, tmp_path: Path) -> None:
        result = _run_command("python3 -c 'import time; time.sleep(60)'", tmp_path, 1)
        assert result is None


# ---------------------------------------------------------------------------
# _check_pytest_cache
# ---------------------------------------------------------------------------

class TestCheckPytestCache:
    def test_pass_when_cache_empty_dict(self, tmp_path: Path) -> None:
        write_pytest_cache(tmp_path, {})
        result = _check_pytest_cache(tmp_path, SESSION_START)
        assert result == "pass"

    def test_fail_when_cache_has_failures(self, tmp_path: Path) -> None:
        write_pytest_cache(tmp_path, {"tests/test_auth.py::test_login": True})
        result = _check_pytest_cache(tmp_path, SESSION_START)
        assert result == "fail"

    def test_none_when_cache_missing(self, tmp_path: Path) -> None:
        result = _check_pytest_cache(tmp_path, SESSION_START)
        assert result is None

    def test_none_when_cache_is_stale(self, tmp_path: Path) -> None:
        cache_dir = tmp_path / ".pytest_cache" / "v" / "cache"
        cache_dir.mkdir(parents=True)
        f = cache_dir / "lastfailed"
        f.write_text("{}")
        # Set mtime to BEFORE session_start
        stale_ts = SESSION_START - 120
        import os
        os.utime(f, (stale_ts, stale_ts))
        result = _check_pytest_cache(tmp_path, SESSION_START)
        assert result is None

    def test_pass_when_cache_content_is_empty_string(self, tmp_path: Path) -> None:
        cache_dir = tmp_path / ".pytest_cache" / "v" / "cache"
        cache_dir.mkdir(parents=True)
        f = cache_dir / "lastfailed"
        f.write_text("")
        import os
        ts = SESSION_START + 10
        os.utime(f, (ts, ts))
        result = _check_pytest_cache(tmp_path, SESSION_START)
        assert result == "pass"


# ---------------------------------------------------------------------------
# _check_junit_xml
# ---------------------------------------------------------------------------

class TestCheckJunitXml:
    def test_pass_when_no_failures(self, tmp_path: Path) -> None:
        write_junit_xml(tmp_path / "junit.xml", failures=0, errors=0)
        result = _check_junit_xml(tmp_path, SESSION_START)
        assert result == "pass"

    def test_fail_when_failures_present(self, tmp_path: Path) -> None:
        write_junit_xml(tmp_path / "junit.xml", failures=2)
        result = _check_junit_xml(tmp_path, SESSION_START)
        assert result == "fail"

    def test_fail_when_errors_present(self, tmp_path: Path) -> None:
        write_junit_xml(tmp_path / "junit.xml", errors=1)
        result = _check_junit_xml(tmp_path, SESSION_START)
        assert result == "fail"

    def test_checks_test_results_xml(self, tmp_path: Path) -> None:
        write_junit_xml(tmp_path / "test-results.xml", failures=0)
        result = _check_junit_xml(tmp_path, SESSION_START)
        assert result == "pass"

    def test_checks_nested_test_results(self, tmp_path: Path) -> None:
        write_junit_xml(tmp_path / "test-results" / "junit.xml", failures=0)
        result = _check_junit_xml(tmp_path, SESSION_START)
        assert result == "pass"

    def test_none_when_no_xml_files(self, tmp_path: Path) -> None:
        result = _check_junit_xml(tmp_path, SESSION_START)
        assert result is None

    def test_none_when_xml_is_stale(self, tmp_path: Path) -> None:
        xml_path = tmp_path / "junit.xml"
        write_junit_xml(xml_path, failures=0)
        stale_ts = SESSION_START - 120
        import os
        os.utime(xml_path, (stale_ts, stale_ts))
        result = _check_junit_xml(tmp_path, SESSION_START)
        assert result is None

    def test_handles_testsuites_wrapper(self, tmp_path: Path) -> None:
        # Some tools wrap with <testsuites><testsuite>
        xml_path = tmp_path / "junit.xml"
        root = ET.Element("testsuites")
        suite = ET.SubElement(root, "testsuite", {
            "failures": "0", "errors": "0", "tests": "5"
        })
        xml_path.write_text(ET.tostring(root, encoding="unicode"))
        import os
        ts = SESSION_START + 10
        os.utime(xml_path, (ts, ts))
        result = _check_junit_xml(tmp_path, SESSION_START)
        assert result == "pass"


# ---------------------------------------------------------------------------
# detect_test_outcome — full pipeline
# ---------------------------------------------------------------------------

class TestDetectTestOutcome:
    def test_priority_1_config_command_used_first(self, tmp_path: Path) -> None:
        # Config has a passing command AND a passing artifact — config wins
        write_pytest_cache(tmp_path, {})
        config = make_config(test_command="python3 -c 'import sys; sys.exit(0)'")
        outcome, source = detect_test_outcome(tmp_path, SESSION_START, config)
        assert outcome == "pass"
        assert source == "config"

    def test_priority_1_fail_from_config(self, tmp_path: Path) -> None:
        config = make_config(test_command="python3 -c 'import sys; sys.exit(1)'")
        outcome, source = detect_test_outcome(tmp_path, SESSION_START, config)
        assert outcome == "fail"
        assert source == "config"

    def test_priority_2_artifact_used_when_no_config(self, tmp_path: Path) -> None:
        write_pytest_cache(tmp_path, {})
        config = make_config(test_command=None)
        outcome, source = detect_test_outcome(tmp_path, SESSION_START, config)
        assert outcome == "pass"
        assert source == "artifact"

    def test_priority_3_none_when_no_signals(self, tmp_path: Path) -> None:
        config = make_config(test_command=None)
        outcome, source = detect_test_outcome(tmp_path, SESSION_START, config)
        assert outcome is None
        assert source is None

    def test_skips_to_artifact_when_command_not_found(self, tmp_path: Path) -> None:
        write_pytest_cache(tmp_path, {"test::fail": True})
        config = make_config(test_command="nonexistent_binary_xyz --run")
        outcome, source = detect_test_outcome(tmp_path, SESSION_START, config)
        # Command not found → falls through to artifact
        assert outcome == "fail"
        assert source == "artifact"
