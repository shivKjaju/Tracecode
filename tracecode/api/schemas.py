"""
api/schemas.py — Pydantic response and request models for the REST API.

All models are read-only except PatchSessionRequest which covers
the three manual-enrichment fields the user can update.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Shared / nested
# ---------------------------------------------------------------------------

class FileTouchOut(BaseModel):
    id: int
    file_path: str
    touch_count: int
    first_touch_at: int        # Unix ms
    last_touch_at: int         # Unix ms
    persisted: int | None      # 1=persisted, 0=reverted, None=unknown
    is_hot: bool               # touch_count >= 3


# ---------------------------------------------------------------------------
# Session list item (lighter — no file touches)
# ---------------------------------------------------------------------------

class SessionSummary(BaseModel):
    id: str
    started_at: int
    ended_at: int | None
    project_name: str
    project_path: str
    git_branch: str | None
    git_commit_before: str | None
    git_commit_after: str | None
    claude_exit_code: int | None
    files_touched: int | None
    hot_files: int | None
    commits_during: int | None
    tree_dirty: int | None
    persistence_rate: float | None
    persistence_reliable: int | None
    test_outcome: str | None
    test_source: str | None
    wandering_score: float | None
    outcome_score: int | None
    quality_score: float | None
    auto_outcome: str | None
    manual_outcome: str | None
    note: str | None
    perceived_quality: int | None
    duration_seconds: int | None


class SessionListResponse(BaseModel):
    sessions: list[SessionSummary]
    total: int
    limit: int
    offset: int


# ---------------------------------------------------------------------------
# Session detail (includes file touches)
# ---------------------------------------------------------------------------

class SessionDetail(SessionSummary):
    file_touches: list[FileTouchOut]


# ---------------------------------------------------------------------------
# Diff response
# ---------------------------------------------------------------------------

class DiffResponse(BaseModel):
    session_id: str
    diff: str       # raw unified diff output
    available: bool # False when git unavailable or no start SHA


# ---------------------------------------------------------------------------
# PATCH request
# ---------------------------------------------------------------------------

class PatchSessionRequest(BaseModel):
    manual_outcome: Literal["success", "partial", "abandoned"] | None = None
    note: str | None = None
    perceived_quality: int | None = None   # 1-5


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    session_count: int
