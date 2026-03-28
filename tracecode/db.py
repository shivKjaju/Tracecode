"""
db.py — SQLite database initialization and CRUD helpers.

All functions take an explicit db_path or an open connection.
No ORM. No connection pool. Raw sqlite3 from stdlib.

Usage:
    init_db(db_path)                    # call once at startup
    with get_conn(db_path) as conn:
        insert_session(conn, {...})
        get_session(conn, session_id)
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS sessions (
    -- Identity
    id                   TEXT    PRIMARY KEY,
    started_at           INTEGER NOT NULL,
    ended_at             INTEGER,
    project_path         TEXT    NOT NULL,
    project_name         TEXT    NOT NULL,

    -- Git state at session boundaries
    git_branch           TEXT,
    git_commit_before    TEXT,
    git_commit_after     TEXT,

    -- Process result
    claude_exit_code     INTEGER,

    -- Watcher-derived (populated during session-end)
    files_touched        INTEGER,
    hot_files            INTEGER,        -- files touched >= 3 times

    -- Git analysis (populated during session-end)
    commits_during       INTEGER,
    tree_dirty           INTEGER,        -- 0 or 1
    persistence_rate     REAL,           -- 0.0-1.0, NULL when unreliable
    persistence_reliable INTEGER DEFAULT 0,  -- 1 if persistence_rate is trustworthy

    -- Test outcome (populated during session-end)
    test_outcome         TEXT,           -- 'pass' | 'fail' | NULL
    test_source          TEXT,           -- 'config' | 'artifact' | NULL

    -- Computed scores (populated during session-end)
    wandering_score      REAL,           -- 0.0-1.0
    outcome_score        INTEGER,        -- 0-4
    quality_score        REAL,           -- 0.0-1.0
    auto_outcome         TEXT,           -- 'success' | 'partial' | 'incomplete'

    -- Manual enrichment — never required, always optional
    manual_outcome       TEXT,           -- 'success' | 'partial' | 'abandoned' | NULL
    note                 TEXT,
    perceived_quality    INTEGER         -- 1-5, dogfooding calibration only
);

CREATE TABLE IF NOT EXISTS file_touches (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT    NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    file_path       TEXT    NOT NULL,       -- relative to project_path
    touch_count     INTEGER NOT NULL DEFAULT 1,
    first_touch_at  INTEGER NOT NULL,       -- Unix milliseconds
    last_touch_at   INTEGER NOT NULL,       -- Unix milliseconds
    persisted       INTEGER                 -- 1=survived to git, 0=reverted, NULL=unknown
);

CREATE TABLE IF NOT EXISTS risky_commands (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT    NOT NULL,   -- may be empty string if guard fires outside a session
    command     TEXT    NOT NULL,
    tier        TEXT    NOT NULL,   -- 'catastrophic' | 'risky'
    reason      TEXT    NOT NULL,
    flagged_at  INTEGER NOT NULL    -- Unix seconds
);

CREATE INDEX IF NOT EXISTS idx_sessions_started      ON sessions(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_project      ON sessions(project_name, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_file_touches_session  ON file_touches(session_id);
CREATE INDEX IF NOT EXISTS idx_file_touches_hot      ON file_touches(session_id, touch_count DESC);
CREATE INDEX IF NOT EXISTS idx_risky_session         ON risky_commands(session_id);
"""

# Columns that may be updated after a session is created.
# Used in update_session() to prevent accidental writes to immutable fields.
_MUTABLE_SESSION_COLUMNS = {
    "ended_at",
    "git_commit_after",
    "claude_exit_code",
    "files_touched",
    "hot_files",
    "commits_during",
    "tree_dirty",
    "persistence_rate",
    "persistence_reliable",
    "test_outcome",
    "test_source",
    "wandering_score",
    "outcome_score",
    "quality_score",
    "auto_outcome",
    "manual_outcome",
    "note",
    "perceived_quality",
}


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

def init_db(db_path: Path) -> None:
    """
    Create the database file and apply the schema.
    Safe to call on an existing database — all statements use IF NOT EXISTS.
    Also ensures the parent directory exists.
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    try:
        # executescript commits any pending transaction first, then runs the SQL
        conn.executescript(SCHEMA_SQL)
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Connection context manager
# ---------------------------------------------------------------------------

@contextmanager
def get_conn(db_path: Path):
    """
    Context manager that yields an open sqlite3 connection.
    Commits on clean exit, rolls back on exception, always closes.

    Usage:
        with get_conn(db_path) as conn:
            conn.execute(...)
    """
    db_path = Path(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row  # rows behave like dicts: row["column_name"]
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Session CRUD
# ---------------------------------------------------------------------------

def insert_session(conn: sqlite3.Connection, session: dict) -> str:
    """
    Insert a new (partial) session row.
    Only the fields present at session start are required:
        id, started_at, project_path, project_name
    git_branch and git_commit_before are optional (None if not a git repo).

    Returns the session id.
    """
    conn.execute(
        """
        INSERT INTO sessions (
            id, started_at, project_path, project_name,
            git_branch, git_commit_before
        ) VALUES (
            :id, :started_at, :project_path, :project_name,
            :git_branch, :git_commit_before
        )
        """,
        {
            "id": session["id"],
            "started_at": session["started_at"],
            "project_path": session["project_path"],
            "project_name": session["project_name"],
            "git_branch": session.get("git_branch"),
            "git_commit_before": session.get("git_commit_before"),
        },
    )
    return session["id"]


def update_session(conn: sqlite3.Connection, session_id: str, **fields) -> None:
    """
    Update named columns on an existing session row.
    Only columns in _MUTABLE_SESSION_COLUMNS are allowed.

    Usage:
        update_session(conn, session_id, ended_at=1234567890, quality_score=0.75)
    """
    if not fields:
        return

    invalid = set(fields.keys()) - _MUTABLE_SESSION_COLUMNS
    if invalid:
        raise ValueError(f"Cannot update read-only session columns: {sorted(invalid)}")

    set_clause = ", ".join(f"{col} = ?" for col in fields)
    values = list(fields.values()) + [session_id]
    conn.execute(f"UPDATE sessions SET {set_clause} WHERE id = ?", values)


def get_session(conn: sqlite3.Connection, session_id: str) -> dict | None:
    """
    Fetch a single session by id. Returns a plain dict or None if not found.
    """
    row = conn.execute(
        "SELECT * FROM sessions WHERE id = ?", (session_id,)
    ).fetchone()
    return dict(row) if row else None


def list_sessions(
    conn: sqlite3.Connection,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """
    Fetch sessions ordered by started_at descending (newest first).
    Returns a list of plain dicts.
    """
    rows = conn.execute(
        "SELECT * FROM sessions ORDER BY started_at DESC LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    return [dict(row) for row in rows]


def count_sessions(conn: sqlite3.Connection) -> int:
    """Return the total number of session rows."""
    return conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]


# ---------------------------------------------------------------------------
# File touch CRUD
# ---------------------------------------------------------------------------

def insert_file_touch(conn: sqlite3.Connection, touch: dict) -> None:
    """
    Insert a single file_touch row.
    Required keys: session_id, file_path, touch_count, first_touch_at, last_touch_at
    Optional: persisted
    """
    conn.execute(
        """
        INSERT INTO file_touches (
            session_id, file_path, touch_count,
            first_touch_at, last_touch_at, persisted
        ) VALUES (
            :session_id, :file_path, :touch_count,
            :first_touch_at, :last_touch_at, :persisted
        )
        """,
        {
            "session_id": touch["session_id"],
            "file_path": touch["file_path"],
            "touch_count": touch["touch_count"],
            "first_touch_at": touch["first_touch_at"],
            "last_touch_at": touch["last_touch_at"],
            "persisted": touch.get("persisted"),
        },
    )


def bulk_insert_file_touches(conn: sqlite3.Connection, touches: list[dict]) -> None:
    """
    Insert multiple file_touch rows in a single transaction.
    More efficient than calling insert_file_touch() in a loop.
    """
    conn.executemany(
        """
        INSERT INTO file_touches (
            session_id, file_path, touch_count,
            first_touch_at, last_touch_at, persisted
        ) VALUES (
            :session_id, :file_path, :touch_count,
            :first_touch_at, :last_touch_at, :persisted
        )
        """,
        [
            {
                "session_id": t["session_id"],
                "file_path": t["file_path"],
                "touch_count": t["touch_count"],
                "first_touch_at": t["first_touch_at"],
                "last_touch_at": t["last_touch_at"],
                "persisted": t.get("persisted"),
            }
            for t in touches
        ],
    )


def get_file_touches(conn: sqlite3.Connection, session_id: str) -> list[dict]:
    """
    Fetch all file touches for a session, sorted by touch_count descending.
    Hot files (touch_count >= 3) naturally appear at the top.
    """
    rows = conn.execute(
        """
        SELECT * FROM file_touches
        WHERE session_id = ?
        ORDER BY touch_count DESC, file_path ASC
        """,
        (session_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def update_file_touch_persisted(
    conn: sqlite3.Connection, touch_id: int, persisted: bool
) -> None:
    """Mark a single file_touch row as persisted or reverted."""
    conn.execute(
        "UPDATE file_touches SET persisted = ? WHERE id = ?",
        (1 if persisted else 0, touch_id),
    )


# ---------------------------------------------------------------------------
# Risky commands
# ---------------------------------------------------------------------------

def get_risky_commands(conn: sqlite3.Connection, session_id: str) -> list[dict]:
    """Return all risky_commands rows for a session, newest first."""
    rows = conn.execute(
        "SELECT * FROM risky_commands WHERE session_id = ? ORDER BY flagged_at DESC",
        (session_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def count_risky_commands(conn: sqlite3.Connection, session_id: str) -> dict:
    """Return {'risky': n, 'catastrophic': n} counts for a session."""
    rows = conn.execute(
        """
        SELECT tier, COUNT(*) as n FROM risky_commands
        WHERE session_id = ?
        GROUP BY tier
        """,
        (session_id,),
    ).fetchall()
    result = {"risky": 0, "catastrophic": 0}
    for r in rows:
        result[r["tier"]] = r["n"]
    return result
