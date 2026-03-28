"""
guard.py — PreToolUse hook for Claude Code.

Reads the tool-use event from stdin (JSON), checks for dangerous bash
patterns, and exits with code 2 + a warning message to block execution,
or exits 0 to allow.

Claude Code hook protocol:
  - stdin: JSON blob with tool name and input
  - stdout: message shown to user (when blocking)
  - exit 0: allow the tool call
  - exit 2: block the tool call; stdout is shown as the reason

Install via ~/.claude/settings.json:
  {
    "hooks": {
      "PreToolUse": [{
        "matcher": "Bash",
        "hooks": [{"type": "command", "command": "~/.tracecode/venv/bin/tracecode guard"}]
      }]
    }
  }
"""

from __future__ import annotations

import json
import re
import sys


# ---------------------------------------------------------------------------
# Dangerous patterns
# Each entry: (regex, human-readable reason)
# ---------------------------------------------------------------------------

_PATTERNS: list[tuple[re.Pattern, str]] = [
    (
        re.compile(r"\brm\s+(-\w*r\w*f|-\w*f\w*r)\s*(\/|~|\.\.|/etc|/usr|/bin|/home|/var|/tmp\s*$|\$HOME|\$\{HOME\})", re.I),
        "recursive force-delete of a system or home directory",
    ),
    (
        re.compile(r"\bsudo\s+rm\b", re.I),
        "sudo rm — elevated file deletion",
    ),
    (
        re.compile(r"curl\s+.*\|\s*(ba)?sh\b", re.I),
        "piping curl output directly to a shell (supply-chain risk)",
    ),
    (
        re.compile(r"wget\s+.*\|\s*(ba)?sh\b", re.I),
        "piping wget output directly to a shell (supply-chain risk)",
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
        "chmod -R 777 opens all files to the world",
    ),
    (
        re.compile(r">\s*/etc/(passwd|shadow|hosts|sudoers)", re.I),
        "overwriting a critical system file",
    ),
    (
        re.compile(r"\bkillall\b|\bkill\s+-9\s+1\b", re.I),
        "killall or killing PID 1 (init/launchd)",
    ),
    (
        re.compile(r"\bdd\s+if=.*of=/dev/(disk|sda|nvme|hd)", re.I),
        "dd writing directly to a disk device",
    ),
    (
        re.compile(r":\(\)\s*\{.*:\|:&\s*\}", re.I),
        "fork bomb detected",
    ),
]


def check_command(command: str) -> str | None:
    """
    Return a warning string if the command matches a dangerous pattern,
    or None if it looks safe.
    """
    for pattern, reason in _PATTERNS:
        if pattern.search(command):
            return reason
    return None


def run() -> None:
    """
    Entry point — reads stdin JSON, checks the bash command, exits accordingly.
    """
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            sys.exit(0)  # no input — allow

        event = json.loads(raw)
    except (json.JSONDecodeError, OSError):
        sys.exit(0)  # can't parse — don't block

    # Extract command from tool input
    tool_input = event.get("tool_input", {})
    command = tool_input.get("command", "")

    if not command:
        sys.exit(0)

    reason = check_command(command)
    if reason:
        print(
            f"tracecode guard: blocked — {reason}\n"
            f"Command: {command[:200]}\n"
            f"If you intend to run this, use TRACECODE_ALLOW=1 to bypass."
        )
        sys.exit(2)

    sys.exit(0)
