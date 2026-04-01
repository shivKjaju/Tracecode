"""
doctor.py — Health checks for `tracecode doctor`.

All checks are pure functions that return a Check dataclass.
No side effects beyond reading files and the database.
Exit code: 0 = all pass, 1 = any fail.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path


# ---------------------------------------------------------------------------
# Paths (mirrored from config.py to avoid loading config for path-level checks)
# ---------------------------------------------------------------------------

_HOME = Path.home()
_TRACECODE_DIR = _HOME / ".tracecode"
_BIN_DIR = _TRACECODE_DIR / "bin"
_WRAPPER = _BIN_DIR / "claude"
_SETTINGS_PATH = _HOME / ".claude" / "settings.json"


# ---------------------------------------------------------------------------
# Check result
# ---------------------------------------------------------------------------

@dataclass
class Check:
    label: str
    passed: bool
    detail: str
    hint: str | None = None   # shown on failure, grouped by unique value


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def check_directory() -> Check:
    exists = _TRACECODE_DIR.exists()
    return Check(
        label="directory",
        passed=exists,
        detail=str(_TRACECODE_DIR),
        hint="tracecode init" if not exists else None,
    )


def check_bin_directory() -> Check:
    exists = _BIN_DIR.exists()
    return Check(
        label="wrapper bin dir",
        passed=exists,
        detail=str(_BIN_DIR),
        hint="tracecode init" if not exists else None,
    )


def check_config() -> Check:
    from tracecode.config import DEFAULT_CONFIG_PATH, load_config

    if not DEFAULT_CONFIG_PATH.exists():
        return Check(
            label="config",
            passed=False,
            detail=f"{DEFAULT_CONFIG_PATH} (not found)",
            hint="tracecode init",
        )
    try:
        load_config(DEFAULT_CONFIG_PATH)
        return Check(label="config", passed=True, detail=str(DEFAULT_CONFIG_PATH))
    except Exception as exc:
        return Check(
            label="config",
            passed=False,
            detail=f"{DEFAULT_CONFIG_PATH} (parse error: {exc})",
            hint="tracecode init",
        )


def check_database() -> Check:
    try:
        from tracecode.config import DEFAULT_CONFIG_PATH, load_config
        config = load_config(DEFAULT_CONFIG_PATH)
        db_path = config.db_path
    except Exception:
        from tracecode.config import DEFAULT_DB_PATH
        db_path = DEFAULT_DB_PATH

    if not db_path.exists():
        return Check(
            label="database",
            passed=False,
            detail=f"{db_path} (not found)",
            hint="tracecode init",
        )
    try:
        conn = sqlite3.connect(str(db_path))
        count = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        conn.close()
        s = "s" if count != 1 else ""
        return Check(
            label="database",
            passed=True,
            detail=f"{db_path} ({count} session{s})",
        )
    except Exception as exc:
        return Check(
            label="database",
            passed=False,
            detail=f"{db_path} ({exc})",
            hint="tracecode init",
        )


def check_claude_binary() -> Check:
    bin_dir = str(_BIN_DIR)
    # Check known install locations first
    candidates = [
        "/usr/local/bin/claude",
        str(_HOME / ".claude" / "local" / "claude"),
        "/opt/homebrew/bin/claude",
    ]
    for c in candidates:
        if Path(c).is_file() and os.access(c, os.X_OK):
            return Check(label="claude binary", passed=True, detail=c)

    # Search PATH, skipping our own wrapper directory
    for dir_str in os.environ.get("PATH", "").split(":"):
        if dir_str == bin_dir:
            continue
        candidate = Path(dir_str) / "claude"
        if candidate.is_file() and os.access(str(candidate), os.X_OK):
            return Check(label="claude binary", passed=True, detail=str(candidate))

    return Check(
        label="claude binary",
        passed=False,
        detail="not found",
        hint="Install Claude Code: https://claude.ai/code",
    )


def check_wrapper() -> Check:
    if _WRAPPER.exists() and os.access(str(_WRAPPER), os.X_OK):
        return Check(label="wrapper", passed=True, detail=f"{_WRAPPER} (active)")
    return Check(
        label="wrapper",
        passed=False,
        detail=f"not found at {_WRAPPER}",
        hint="./scripts/install.sh",
    )


def check_path_order() -> Check:
    resolved = shutil.which("claude")
    if resolved is None:
        return Check(
            label="PATH order",
            passed=False,
            detail="claude not found in PATH",
            hint=(
                'source ~/.zshrc\n'
                '  Or add to your shell rc:\n'
                '    export PATH="$HOME/.tracecode/bin:$PATH"'
            ),
        )
    try:
        is_wrapper = Path(resolved).resolve() == _WRAPPER.resolve()
    except OSError:
        is_wrapper = False

    if is_wrapper:
        return Check(label="PATH order", passed=True, detail="claude → wrapper ✓")

    return Check(
        label="PATH order",
        passed=False,
        detail=f"claude resolves to {resolved} — wrapper not intercepting",
        hint=(
            'source ~/.zshrc\n'
            '  Or add to your shell rc:\n'
            '    export PATH="$HOME/.tracecode/bin:$PATH"'
        ),
    )


def _load_settings() -> dict:
    if not _SETTINGS_PATH.exists():
        return {}
    try:
        return json.loads(_SETTINGS_PATH.read_text())
    except Exception:
        return {}


def check_hooks_file() -> Check:
    if not _SETTINGS_PATH.exists():
        return Check(
            label="hooks file",
            passed=False,
            detail=f"not found at {_SETTINGS_PATH}",
            hint="tracecode install-guard",
        )
    try:
        json.loads(_SETTINGS_PATH.read_text())
        return Check(label="hooks file", passed=True, detail=str(_SETTINGS_PATH))
    except json.JSONDecodeError:
        return Check(
            label="hooks file",
            passed=False,
            detail=f"{_SETTINGS_PATH} (invalid JSON)",
            hint="tracecode install-guard",
        )


def check_guard_hook() -> Check:
    settings = _load_settings()
    pre = settings.get("hooks", {}).get("PreToolUse", [])
    installed = any(
        "tracecode" in h.get("command", "") and "guard" in h.get("command", "")
        for entry in pre
        if isinstance(entry, dict) and entry.get("matcher") == "Bash"
        for h in entry.get("hooks", [])
        if isinstance(h, dict)
    )
    if installed:
        return Check(
            label="guard hook",
            passed=True,
            detail="PreToolUse → tracecode guard",
        )
    return Check(
        label="guard hook",
        passed=False,
        detail="not installed",
        hint="tracecode install-guard",
    )


def check_checkpoint_hook() -> Check:
    settings = _load_settings()
    post = settings.get("hooks", {}).get("PostToolUse", [])
    installed = any(
        "tracecode" in h.get("command", "") and "checkpoint" in h.get("command", "")
        for entry in post
        if isinstance(entry, dict) and entry.get("matcher") == "Bash"
        for h in entry.get("hooks", [])
        if isinstance(h, dict)
    )
    if installed:
        return Check(
            label="checkpoint hook",
            passed=True,
            detail="PostToolUse → tracecode checkpoint",
        )
    return Check(
        label="checkpoint hook",
        passed=False,
        detail="not installed",
        hint="tracecode install-guard",
    )


# ---------------------------------------------------------------------------
# Run all checks
# ---------------------------------------------------------------------------

def run_checks() -> list[Check]:
    return [
        check_directory(),
        check_bin_directory(),
        check_config(),
        check_database(),
        check_claude_binary(),
        check_wrapper(),
        check_path_order(),
        check_hooks_file(),
        check_guard_hook(),
        check_checkpoint_hook(),
    ]
