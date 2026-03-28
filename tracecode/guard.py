"""
guard.py — PreToolUse hook for Claude Code.

Two tiers:

  CATASTROPHIC — blocked outright (exit 2). No recovery path, machine/OS
                 destroying in one shot. User must intervene at OS level.

  RISKY        — logged to DB, allowed (exit 0). Claude's own permission
                 prompt still fires; Tracecode records the attempt so the
                 session detail shows what risky commands were run.

Claude Code hook protocol:
  - stdin: JSON blob with tool name and input
  - stdout: message shown when blocking (exit 2)
  - exit 0: allow  |  exit 2: block
"""

from __future__ import annotations

import json
import re
import sys
import time


# ---------------------------------------------------------------------------
# Pattern tiers
# ---------------------------------------------------------------------------

# Blocked outright — no recovery possible
_CATASTROPHIC: list[tuple[re.Pattern, str]] = [
    (
        re.compile(r"\brm\s+(-\w*r\w*f|-\w*f\w*r)\s*(/\s*$|/\s+|~\s*$|~\s+|\$HOME\s*$|\$\{HOME\}\s*$)", re.I),
        "recursive force-delete of / or home directory",
    ),
    (
        re.compile(r"\bdd\s+if=.*of=/dev/(disk|sda|nvme|hda|vda)", re.I),
        "dd writing directly to a disk device — will destroy all data",
    ),
    (
        re.compile(r":\(\)\s*\{.*:\|:&\s*\}", re.I),
        "fork bomb — will crash the OS",
    ),
    (
        re.compile(r">\s*/etc/(passwd|shadow|sudoers)", re.I),
        "overwriting a critical system auth file",
    ),
]

# Logged and allowed — Claude's permission prompt still fires
_RISKY: list[tuple[re.Pattern, str]] = [
    (
        re.compile(r"\bsudo\s+rm\b", re.I),
        "sudo rm — elevated file deletion",
    ),
    (
        re.compile(r"curl\s+.*\|\s*(ba)?sh\b", re.I),
        "curl piped to shell (supply-chain risk)",
    ),
    (
        re.compile(r"wget\s+.*\|\s*(ba)?sh\b", re.I),
        "wget piped to shell (supply-chain risk)",
    ),
    (
        re.compile(r"\bgit\s+push\s+.*--force\b.*\b(main|master)\b", re.I),
        "force-push to main/master",
    ),
    (
        re.compile(r"\bgit\s+push\s+.*\b(main|master)\b.*--force\b", re.I),
        "force-push to main/master",
    ),
    (
        re.compile(r"\b(DROP\s+TABLE|DROP\s+DATABASE|TRUNCATE\s+TABLE)\b", re.I),
        "destructive SQL statement",
    ),
    (
        re.compile(r"\bchmod\s+-R\s+777\b", re.I),
        "chmod -R 777 makes all files world-writable",
    ),
    (
        re.compile(r"\bkillall\b", re.I),
        "killall — terminates all matching processes",
    ),
    (
        re.compile(r"\brm\s+(-\w*r\w*f|-\w*f\w*r)\b", re.I),
        "recursive force-delete",
    ),
]


def _classify(command: str) -> tuple[str, str] | None:
    """
    Returns ("catastrophic", reason) | ("risky", reason) | None if clean.
    """
    for pattern, reason in _CATASTROPHIC:
        if pattern.search(command):
            return ("catastrophic", reason)
    for pattern, reason in _RISKY:
        if pattern.search(command):
            return ("risky", reason)
    return None


def _current_session_id() -> str:
    """
    Read the session ID written by the wrapper to ~/.tracecode/current_session.
    Returns empty string if no session is active (guard fired outside a wrapper).
    """
    try:
        from pathlib import Path
        f = Path.home() / ".tracecode" / "current_session"
        return f.read_text().strip() if f.exists() else ""
    except OSError:
        return ""


def _log_to_db(session_id: str, command: str, tier: str, reason: str) -> None:
    """
    Write to risky_commands table. Silent on any failure — never block
    the guard flow due to a DB error.
    """
    try:
        from pathlib import Path
        from tracecode.db import get_conn
        db = Path.home() / ".tracecode" / "tracecode.db"
        with get_conn(db) as conn:
            conn.execute(
                """
                INSERT INTO risky_commands
                    (session_id, command, tier, reason, flagged_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, command[:500], tier, reason, int(time.time())),
            )
    except Exception:
        pass


def run() -> None:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            sys.exit(0)
        event = json.loads(raw)
    except (json.JSONDecodeError, OSError):
        sys.exit(0)

    tool_input = event.get("tool_input", {})
    command = tool_input.get("command", "")
    session_id = _current_session_id()

    if not command:
        sys.exit(0)

    result = _classify(command)
    if result is None:
        sys.exit(0)

    tier, reason = result

    if tier == "catastrophic":
        print(
            f"tracecode: BLOCKED — {reason}\n"
            f"This command can cause irreversible damage and has been stopped.\n"
            f"Command: {command[:200]}"
        )
        _log_to_db(session_id, command, tier, reason)
        sys.exit(2)

    # risky — log and allow (Claude's permission prompt handles the UX)
    _log_to_db(session_id, command, tier, reason)
    sys.exit(0)
