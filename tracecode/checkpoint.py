"""
checkpoint.py — PostToolUse hook for Claude Code.

Reads unnotified runtime events from session_events and outputs checkpoint
messages to stdout. Claude Code includes hook stdout in the tool result, so
Claude reads these as part of the response to its last tool call.

Each event fires at most once per session — the notified flag prevents repeats.
Silent on any error — never interrupts the session.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path


def _current_session_id() -> str:
    try:
        f = Path.home() / ".tracecode" / "current_session"
        return f.read_text().strip() if f.exists() else ""
    except OSError:
        return ""


def _format_message(event_type: str, payload: dict) -> str | None:
    if event_type == "blast_radius":
        n = payload.get("unique_files", "many")
        w = payload.get("window_seconds", 90)
        return (
            f"[tracecode checkpoint] Blast radius expanding — "
            f"{n} unique files modified in {w}s. "
            f"Consider pausing to confirm scope before continuing."
        )
    if event_type == "file_churn":
        path = payload.get("file_path", "a file")
        count = payload.get("touch_count", "many")
        return (
            f"[tracecode checkpoint] File churn — "
            f"{path} modified {count} times. Agent may be stuck or looping."
        )
    if event_type == "sensitive_file_warned":
        path = payload.get("file_path", "a sensitive file")
        return (
            f"[tracecode warning] Sensitive file modified: {path}"
            f" — verify this change is intentional."
        )
    if event_type == "risky_accumulation":
        count = payload.get("count", 3)
        return (
            f"[tracecode checkpoint] {count} risky commands used so far this session. "
            f"Review flagged commands before continuing."
        )
    return None


def run() -> None:
    # Consume stdin — Claude Code provides the tool event; we don't need it
    try:
        sys.stdin.read()
    except OSError:
        pass

    session_id = _current_session_id()
    if not session_id:
        sys.exit(0)

    db = Path.home() / ".tracecode" / "tracecode.db"
    if not db.exists():
        sys.exit(0)

    messages: list[str] = []

    try:
        from tracecode.db import get_conn
        with get_conn(db) as conn:
            # 1. Flush all unnotified session_events for this session
            rows = conn.execute(
                "SELECT * FROM session_events"
                " WHERE session_id = ? AND notified = 0"
                " ORDER BY fired_at ASC",
                (session_id,),
            ).fetchall()
            for row in rows:
                payload = json.loads(row["payload"]) if row["payload"] else {}
                msg = _format_message(row["event_type"], payload)
                if msg:
                    messages.append(msg)
                conn.execute(
                    "UPDATE session_events SET notified = 1 WHERE id = ?",
                    (row["id"],),
                )

            # 2. Risky accumulation — derived from risky_commands, not watcher
            #    Only fires once: check whether we already recorded this event
            already_fired = conn.execute(
                "SELECT 1 FROM session_events"
                " WHERE session_id = ? AND event_type = 'risky_accumulation'",
                (session_id,),
            ).fetchone()
            if not already_fired:
                risky_count = conn.execute(
                    "SELECT COUNT(*) FROM risky_commands"
                    " WHERE session_id = ? AND tier = 'risky'",
                    (session_id,),
                ).fetchone()[0]
                if risky_count >= 3:
                    payload = {"count": risky_count}
                    msg = _format_message("risky_accumulation", payload)
                    if msg:
                        messages.append(msg)
                    conn.execute(
                        "INSERT INTO session_events"
                        " (session_id, event_type, payload, fired_at, notified)"
                        " VALUES (?, 'risky_accumulation', ?, ?, 1)",
                        (session_id, json.dumps(payload), int(time.time())),
                    )
    except Exception:
        sys.exit(0)

    if messages:
        print("\n".join(messages))

    sys.exit(0)
