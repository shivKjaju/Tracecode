"""
api/schemas.py — Pydantic response and request models for the REST API.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class Anomaly(BaseModel):
    id: str
    label: str
    detail: str
    severity: str  # "major" | "minor" | "caution"


class FileTouchOut(BaseModel):
    id: int
    file_path: str
    touch_count: int
    first_touch_at: int
    last_touch_at: int
    persisted: int | None
    is_hot: bool


class OutcomeSignal(BaseModel):
    label: str
    passed: bool
    reliable: bool


class RiskyCommandOut(BaseModel):
    id: int
    command: str
    tier: str
    reason: str
    flagged_at: int


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
    ignored_touches: int | None
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
    risky_count: int
    catastrophic_count: int
    verdict: str | None
    sensitive_files_touched: int | None


class SessionListResponse(BaseModel):
    sessions: list[SessionSummary]
    total: int
    limit: int
    offset: int


class SessionDetail(SessionSummary):
    file_touches: list[FileTouchOut]
    risky_commands: list[RiskyCommandOut]
    outcome_signals: list[OutcomeSignal]
    anomalies: list[Anomaly]


class DiffResponse(BaseModel):
    session_id: str
    diff: str
    available: bool


class PatchSessionRequest(BaseModel):
    manual_outcome: Literal["success", "partial", "abandoned"] | None = None
    note: str | None = None
    perceived_quality: int | None = None


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    session_count: int
