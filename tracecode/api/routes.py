"""
api/routes.py — All REST API route handlers.

Routes:
  GET  /api/health
  GET  /api/sessions
  GET  /api/sessions/{session_id}
  GET  /api/sessions/{session_id}/diff
  PATCH /api/sessions/{session_id}

Internal helpers:
  _build_session_detail()  — shared logic used by GET and PATCH detail routes.
                             Both routes need the same: fetch → score → build response.
                             Keeping it in one place means a change to anomaly logic
                             or review_first ranking only needs to happen once.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from tracecode.api.schemas import (
    Anomaly,
    DiffResponse,
    FileTouchOut,
    HealthResponse,
    OutcomeSignal,
    PatchSessionRequest,
    ReviewFirstFile,
    RiskyCommandOut,
    RuntimeEventOut,
    SessionDetail,
    SessionListResponse,
    SessionSummary,
)
from tracecode.config import DEFAULT_CONFIG_PATH, load_config
from tracecode.db import (
    count_sessions,
    count_risky_commands,
    get_conn,
    get_file_touches,
    get_risky_commands,
    get_session,
    get_session_events,
    list_sessions,
    update_session,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Dependency: config
# ---------------------------------------------------------------------------

def _config():
    return load_config(DEFAULT_CONFIG_PATH)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _validate_session_id(session_id: str) -> None:
    """Raise 400 if session_id is not a valid UUID. Prevents crafted path inputs."""
    try:
        UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session ID format")

def _session_to_summary(row: dict, risk_counts: dict | None = None) -> SessionSummary:
    started = row.get("started_at") or 0
    ended = row.get("ended_at")
    duration = (ended - started) if ended else None
    counts = risk_counts or {"risky": 0, "catastrophic": 0}
    return SessionSummary(
        id=row["id"],
        started_at=row["started_at"],
        ended_at=row.get("ended_at"),
        project_name=row["project_name"],
        project_path=row["project_path"],
        git_branch=row.get("git_branch"),
        git_commit_before=row.get("git_commit_before"),
        git_commit_after=row.get("git_commit_after"),
        claude_exit_code=row.get("claude_exit_code"),
        files_touched=row.get("files_touched"),
        hot_files=row.get("hot_files"),
        commits_during=row.get("commits_during"),
        tree_dirty=row.get("tree_dirty"),
        persistence_rate=row.get("persistence_rate"),
        persistence_reliable=row.get("persistence_reliable"),
        test_outcome=row.get("test_outcome"),
        test_source=row.get("test_source"),
        wandering_score=row.get("wandering_score"),
        outcome_score=row.get("outcome_score"),
        quality_score=row.get("quality_score"),
        auto_outcome=row.get("auto_outcome"),
        manual_outcome=row.get("manual_outcome"),
        note=row.get("note"),
        perceived_quality=row.get("perceived_quality"),
        duration_seconds=duration,
        risky_count=counts["risky"],
        catastrophic_count=counts["catastrophic"],
        ignored_touches=row.get("ignored_touches"),
        verdict=row.get("verdict"),
        sensitive_files_touched=row.get("sensitive_files_touched"),
    )


def _build_session_detail(session_id: str, conn) -> SessionDetail:
    """
    Fetch a session from the DB and build a fully-populated SessionDetail response.

    Called by both GET /sessions/{id} and PATCH /sessions/{id} — the only difference
    between those two routes is that PATCH writes updates first, then calls this.
    """
    from tracecode.analysis.scoring import (
        compute_anomalies,
        compute_outcome_signals,
        compute_review_first,
        compute_verdict,
    )

    row = get_session(conn, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")

    touches            = get_file_touches(conn, session_id)
    risks              = get_risky_commands(conn, session_id)
    risk_counts        = count_risky_commands(conn, session_id)
    runtime_events_raw = get_session_events(conn, session_id)

    signals   = [OutcomeSignal(**s) for s in compute_outcome_signals(row)]
    anomalies = compute_anomalies(row, touches, risks, runtime_events_raw)

    # Use the stored verdict if present; recompute (and persist) if the session
    # ended but verdict is missing (e.g. analysis crashed or pre-verdict migration).
    verdict = row.get("verdict")
    if not verdict and row.get("ended_at") is not None:
        verdict = compute_verdict(
            risk_counts["catastrophic"], risk_counts["risky"], anomalies
        )
        if verdict:
            update_session(conn, session_id, verdict=verdict)

    review_first = compute_review_first(
        file_touches=touches,
        risky_commands=risks,
        session_verdict=verdict,
        diff_lines=row.get("diff_lines"),
    )

    _checkpoint_types = {"blast_radius", "file_churn", "risky_accumulation"}
    checkpoint_fired = any(
        e["event_type"] in _checkpoint_types for e in runtime_events_raw
    )
    runtime_warning_count = sum(
        1 for e in runtime_events_raw if e["event_type"] == "sensitive_file_warned"
    )

    summary = _session_to_summary(row, risk_counts)
    if not summary.verdict:
        summary = summary.model_copy(update={"verdict": verdict})

    return SessionDetail(
        **summary.model_dump(),
        file_touches=[_touch_to_out(t) for t in touches],
        risky_commands=[_risk_to_out(r) for r in risks],
        outcome_signals=signals,
        anomalies=[Anomaly(**a) for a in anomalies],
        runtime_events=[RuntimeEventOut(**e) for e in runtime_events_raw],
        checkpoint_fired=checkpoint_fired,
        runtime_warning_count=runtime_warning_count,
        review_first=[ReviewFirstFile(**f) for f in review_first],
    )


def _risk_to_out(row: dict) -> RiskyCommandOut:
    return RiskyCommandOut(
        id=row["id"],
        command=row["command"],
        tier=row["tier"],
        reason=row["reason"],
        flagged_at=row["flagged_at"],
    )


def _touch_to_out(row: dict) -> FileTouchOut:
    return FileTouchOut(
        id=row["id"],
        file_path=row["file_path"],
        touch_count=row["touch_count"],
        first_touch_at=row["first_touch_at"],
        last_touch_at=row["last_touch_at"],
        persisted=row.get("persisted"),
        is_hot=row["touch_count"] >= 3,
    )


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@router.get("/health", response_model=HealthResponse)
def health(config=Depends(_config)):
    with get_conn(config.db_path) as conn:
        total = count_sessions(conn)
    return HealthResponse(session_count=total)


# ---------------------------------------------------------------------------
# Sessions list
# ---------------------------------------------------------------------------

@router.get("/sessions", response_model=SessionListResponse)
def list_sessions_route(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    config=Depends(_config),
):
    with get_conn(config.db_path) as conn:
        rows = list_sessions(conn, limit=limit, offset=offset)
        total = count_sessions(conn)
        summaries = [
            _session_to_summary(r, count_risky_commands(conn, r["id"]))
            for r in rows
        ]

    return SessionListResponse(
        sessions=summaries,
        total=total,
        limit=limit,
        offset=offset,
    )


# ---------------------------------------------------------------------------
# Session detail
# ---------------------------------------------------------------------------

@router.get("/sessions/{session_id}", response_model=SessionDetail)
def get_session_route(session_id: str, config=Depends(_config)):
    _validate_session_id(session_id)
    with get_conn(config.db_path) as conn:
        return _build_session_detail(session_id, conn)


# ---------------------------------------------------------------------------
# Diff  (on-demand git diff)
# ---------------------------------------------------------------------------

@router.get("/sessions/{session_id}/diff", response_model=DiffResponse)
def get_diff_route(session_id: str, config=Depends(_config)):
    _validate_session_id(session_id)
    with get_conn(config.db_path) as conn:
        row = get_session(conn, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")

    project_path = row.get("project_path", "")
    start_sha = row.get("git_commit_before", "")

    if not project_path or not start_sha:
        return DiffResponse(session_id=session_id, diff="", available=False)

    try:
        from tracecode.capture.git import get_net_diff, is_git_repo
        if not is_git_repo(project_path):
            return DiffResponse(session_id=session_id, diff="", available=False)
        diff = get_net_diff(project_path, start_sha)
        return DiffResponse(session_id=session_id, diff=diff or "", available=True)
    except Exception:
        return DiffResponse(session_id=session_id, diff="", available=False)


# ---------------------------------------------------------------------------
# PATCH session (manual enrichment)
# ---------------------------------------------------------------------------

@router.patch("/sessions/{session_id}", response_model=SessionDetail)
def patch_session_route(
    session_id: str,
    body: PatchSessionRequest,
    config=Depends(_config),
):
    _validate_session_id(session_id)
    with get_conn(config.db_path) as conn:
        row = get_session(conn, session_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Session not found")

        updates = body.model_dump(exclude_unset=True)
        pq = updates.get("perceived_quality")
        if pq is not None and not (1 <= pq <= 5):
            raise HTTPException(status_code=422, detail="perceived_quality must be 1-5")

        if updates:
            update_session(conn, session_id, **updates)

        # Write updates first, then build the response from the updated row.
        return _build_session_detail(session_id, conn)
