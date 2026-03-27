"""
models.py — Python dataclasses mirroring the database schema.

These are used as typed containers when passing session and file touch data
between modules. They map 1:1 to db.py's table columns.

Note: SQLite stores booleans as INTEGER (0/1). These dataclasses use bool
for clarity, but db.py handles the int/bool conversion at the boundary.
"""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Session:
    # --- Required at creation ---
    id: str
    started_at: int                  # Unix seconds
    project_path: str
    project_name: str

    # --- Optional at creation, set post-session ---
    ended_at: int | None = None
    git_branch: str | None = None
    git_commit_before: str | None = None
    git_commit_after: str | None = None
    claude_exit_code: int | None = None

    # --- Watcher-derived ---
    files_touched: int | None = None
    hot_files: int | None = None     # files touched >= 3 times

    # --- Git analysis ---
    commits_during: int | None = None
    tree_dirty: bool | None = None
    persistence_rate: float | None = None
    persistence_reliable: bool = False

    # --- Test outcome ---
    test_outcome: str | None = None  # 'pass' | 'fail' | None
    test_source: str | None = None   # 'config' | 'artifact' | None

    # --- Computed scores ---
    wandering_score: float | None = None
    outcome_score: int | None = None
    quality_score: float | None = None
    auto_outcome: str | None = None  # 'success' | 'partial' | 'incomplete'

    # --- Manual enrichment (never required) ---
    manual_outcome: str | None = None  # 'success' | 'partial' | 'abandoned'
    note: str | None = None
    perceived_quality: int | None = None  # 1-5, calibration only

    @property
    def duration_seconds(self) -> int | None:
        """Convenience: session duration in seconds, or None if not ended."""
        if self.started_at is not None and self.ended_at is not None:
            return self.ended_at - self.started_at
        return None

    @property
    def effective_outcome(self) -> str | None:
        """Returns manual_outcome if set, otherwise auto_outcome."""
        return self.manual_outcome or self.auto_outcome

    @classmethod
    def from_dict(cls, d: dict) -> "Session":
        """
        Construct a Session from a plain dict (e.g. a sqlite3.Row converted to dict).
        Unknown keys are silently ignored so this stays safe as the schema evolves.
        """
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        filtered = {k: v for k, v in d.items() if k in known}
        # Convert SQLite INTEGER booleans back to Python bool
        for bool_field in ("tree_dirty", "persistence_reliable"):
            if bool_field in filtered and filtered[bool_field] is not None:
                filtered[bool_field] = bool(filtered[bool_field])
        return cls(**filtered)


@dataclass
class FileTouch:
    session_id: str
    file_path: str               # relative to project_path
    touch_count: int
    first_touch_at: int          # Unix milliseconds
    last_touch_at: int           # Unix milliseconds

    # Set during post-session persistence analysis
    persisted: bool | None = None

    # Set by the database on insert
    id: int | None = None

    @property
    def is_hot(self) -> bool:
        """A file touched 3 or more times is considered a 'hot file' (wandering signal)."""
        return self.touch_count >= 3

    @classmethod
    def from_dict(cls, d: dict) -> "FileTouch":
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        filtered = {k: v for k, v in d.items() if k in known}
        if "persisted" in filtered and filtered["persisted"] is not None:
            filtered["persisted"] = bool(filtered["persisted"])
        return cls(**filtered)
