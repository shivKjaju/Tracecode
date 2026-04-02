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

──────────────────────────────────────────────────────────────────────────────
ADDING NEW PATTERNS
──────────────────────────────────────────────────────────────────────────────

Both _CATASTROPHIC and _RISKY are plain lists of (compiled_regex, reason_string).
Add a new tuple anywhere in the list — order does not matter.

Format:
    (
        re.compile(r"<your regex here>", re.I),
        "<short human-readable reason — shown in the UI and block message>",
    ),

Tier criteria
─────────────
  CATASTROPHIC — all three must be true:
    1. Irreversible in a single command (no undo, no recycle bin, no git)
    2. Affects the OS, disk, or system-wide paths — not just the project
    3. A reasonable Claude session would never need this command

  RISKY — one or more:
    • Elevated privileges (sudo) operating on files
    • Destroys data that is recoverable with effort (e.g. git history, DB tables)
    • Modifies access controls or process state in ways that affect other programs
    • If you are unsure: add it here, not to CATASTROPHIC

Regex tips
──────────
  • Use re.I (case-insensitive) — shell commands can be mixed case
  • Use \b word boundaries to avoid matching substrings (e.g. \bsudo\b)
  • Prefer specific over broad — a false positive that blocks a safe command
    is worse than a false negative that lets a risky one through
  • Test with: pytest tests/test_guard.py -v
  • The command string passed in is the raw bash input — may include pipes,
    semicolons, subshells, env var expansions, and quoted strings

Examples
────────
  # Block any command that overwrites /boot
  (re.compile(r"(>|tee)\s*/boot/", re.I), "writing to /boot"),

  # Flag use of shred (irreversible file wipe)
  (re.compile(r"\bshred\b", re.I), "shred — irreversible file wipe"),
"""

from __future__ import annotations

import json
import re
import sys
import time


# ---------------------------------------------------------------------------
# Catastrophic patterns — blocked outright, no recovery possible
# ---------------------------------------------------------------------------
#
# Categories:
#   [filesystem]   — deletes or destroys files/disks at OS level
#   [code exec]    — runs untrusted code from the network
#   [system files] — overwrites critical OS configuration

_CATASTROPHIC: list[tuple[re.Pattern, str]] = [
    # [filesystem] recursive force-delete of / or home
    (
        re.compile(r"\brm\s+(-\w*r\w*f|-\w*f\w*r)\s*(/\s*$|/\s+|~\s*$|~\s+|\$HOME\s*$|\$\{HOME\}\s*$)", re.I),
        "recursive force-delete of / or home directory",
    ),
    # [filesystem] dd writing directly to raw disk
    (
        re.compile(r"\bdd\s+if=.*of=/dev/(disk|sda|nvme|hda|vda)", re.I),
        "dd writing directly to a disk device — will destroy all data",
    ),
    # [filesystem] fork bomb — exhausts OS process table
    (
        re.compile(r":\(\)\s*\{.*:\|:&\s*\}", re.I),
        "fork bomb — will crash the OS",
    ),
    # [system files] overwrite auth files
    (
        re.compile(r">\s*/etc/(passwd|shadow|sudoers)", re.I),
        "overwriting a critical system auth file",
    ),
    # [code exec] curl/wget piped to a shell
    (
        re.compile(r"curl\s+\S.*\|\s*(ba)?sh\b", re.I),
        "curl piped to shell — supply-chain code execution risk",
    ),
    (
        re.compile(r"wget\s+\S.*\|\s*(ba)?sh\b", re.I),
        "wget piped to shell — supply-chain code execution risk",
    ),
    # [system files] writing to system binary/config directories
    (
        re.compile(r"(>|tee)\s*/(?:etc|usr/local/bin|usr/bin|bin|sbin)/", re.I),
        "writing to a system path outside project scope",
    ),
]

# ---------------------------------------------------------------------------
# Risky patterns — logged and allowed, Claude's permission prompt still fires
# ---------------------------------------------------------------------------
#
# Categories:
#   [filesystem]  — elevated or recursive deletes within the project
#   [git]         — destructive git operations
#   [database]    — irreversible SQL
#   [permissions] — modifies file or process access controls

_RISKY: list[tuple[re.Pattern, str]] = [
    # [filesystem]
    (
        re.compile(r"\bsudo\s+rm\b", re.I),
        "sudo rm — elevated file deletion",
    ),
    (
        re.compile(r"\brm\s+(-\w*r\w*f|-\w*f\w*r)\b", re.I),
        "recursive force-delete",
    ),
    # [git]
    (
        re.compile(r"\bgit\s+push\s+.*--force\b.*\b(main|master)\b", re.I),
        "force-push to main/master",
    ),
    (
        re.compile(r"\bgit\s+push\s+.*\b(main|master)\b.*--force\b", re.I),
        "force-push to main/master",
    ),
    # [database]
    (
        re.compile(r"\b(DROP\s+TABLE|DROP\s+DATABASE|TRUNCATE\s+TABLE)\b", re.I),
        "destructive SQL statement",
    ),
    # [permissions]
    (
        re.compile(r"\bchmod\s+-R\s+777\b", re.I),
        "chmod -R 777 makes all files world-writable",
    ),
    (
        re.compile(r"\bkillall\b", re.I),
        "killall — terminates all matching processes",
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

    # risky — log, warn on stderr, and allow (Claude's permission prompt handles the UX)
    _log_to_db(session_id, command, tier, reason)
    print(f"[tracecode] \u26a0 risky: {reason}", file=sys.stderr)
    sys.exit(0)
