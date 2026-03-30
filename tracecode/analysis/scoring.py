"""
analysis/scoring.py — Session quality score computations.

All functions are pure: no I/O, no DB access, no side effects.
Input is plain Python values. Output is a plain dict or a single value.

Scoring philosophy:
  - Simple heuristics, not ML
  - Directionally correct > precisely wrong
  - Formula weights will be adjusted after dogfooding
  - When a signal is unavailable, it is omitted cleanly (not zeroed)
"""

import re


def compute_wandering_score(files_touched: int, hot_files: int) -> float:
    """
    Fraction of touched files that were 'hot' (edited 3+ times).
    0.0 = every file touched once or twice (focused session).
    1.0 = every file was repeatedly edited (thrashing).

    Returns 0.0 if no files were touched (e.g. chat-only session).
    """
    if files_touched == 0:
        return 0.0
    return round(min(1.0, hot_files / files_touched), 3)


def compute_outcome_score(
    commits_during: int,
    tree_dirty: bool,
    test_outcome: str | None,
    persistence_rate: float | None,
    persistence_reliable: bool,
) -> int:
    """
    Integer 0–4. One point for each positive signal:
      +1  a commit was made during the session
      +1  working tree is clean at session end
      +1  test suite passed
      +1  >= 70% of touched files persisted (only counted when reliable)

    Missing signals are simply not counted (not penalised).
    Max possible score is 3 when test outcome is unknown, 4 when known.
    """
    score = 0
    if commits_during and commits_during > 0:
        score += 1
    if not tree_dirty:
        score += 1
    if test_outcome == "pass":
        score += 1
    if persistence_reliable and persistence_rate is not None:
        if persistence_rate >= 0.7:
            score += 1
    return score


def compute_quality_score(
    outcome_score: int,
    wandering_score: float,
    persistence_rate: float | None,
    persistence_reliable: bool,
) -> float:
    """
    Composite quality score 0.0–1.0.

    When persistence is reliable (3-signal variant):
        outcome   55%   primary signal
        wandering 25%   efficiency signal
        persists  20%   agent acceptance signal

    When persistence is unreliable or unavailable (2-signal variant):
        outcome   60%
        wandering 40%

    The denominator for outcome_score is always 4 (maximum possible points)
    regardless of how many signals were actually available. This keeps the
    scale consistent across sessions with different data completeness.
    """
    if persistence_reliable and persistence_rate is not None:
        return round(
            (outcome_score / 4.0) * 0.55
            + (1.0 - wandering_score) * 0.25
            + persistence_rate * 0.20,
            3,
        )
    else:
        return round(
            (outcome_score / 4.0) * 0.60
            + (1.0 - wandering_score) * 0.40,
            3,
        )


def classify_outcome(outcome_score: int) -> str:
    """
    Map outcome_score to a human-readable label.
      3–4 → success
      1–2 → partial
      0   → incomplete
    """
    if outcome_score >= 3:
        return "success"
    if outcome_score >= 1:
        return "partial"
    return "incomplete"


def compute_outcome_signals(session: dict) -> list[dict]:
    """
    Return the four outcome signals as a list of dicts, each with:
      label      — human-readable signal name
      passed     — whether this signal is positive
      reliable   — whether the signal has real data (False = no data available)

    Used by the API so the UI can render a checklist instead of an opaque score.
    """
    commits_during  = int(session.get("commits_during") or 0)
    tree_dirty      = bool(session.get("tree_dirty"))
    test_outcome    = session.get("test_outcome")
    persistence_rate     = session.get("persistence_rate")
    persistence_reliable = bool(session.get("persistence_reliable"))

    return [
        {
            "label":    "Committed code",
            "passed":   commits_during > 0,
            "reliable": session.get("commits_during") is not None,
        },
        {
            "label":    "Clean tree at end",
            "passed":   not tree_dirty,
            "reliable": session.get("tree_dirty") is not None,
        },
        {
            "label":    "Tests passed",
            "passed":   test_outcome == "pass",
            "reliable": test_outcome is not None,
        },
        {
            "label":    "Files persisted to git",
            "passed":   persistence_reliable and persistence_rate is not None and persistence_rate >= 0.7,
            "reliable": persistence_reliable and persistence_rate is not None,
        },
    ]


# ---------------------------------------------------------------------------
# Sensitive file detection
# ---------------------------------------------------------------------------

_SENSITIVE_EXACT = frozenset({
    "package.json", "requirements.txt", "Gemfile", "Cargo.toml",
    "go.mod", "pyproject.toml", "Dockerfile",
})

_SENSITIVE_PATTERNS = [
    re.compile(r'(^|[/\\])\.env(\.|$|[/\\])'),   # .env.local, .env.production …
    re.compile(r'(^|[/\\])\.env$'),               # bare .env
    re.compile(r'\.(pem|key|p12|pfx|crt|cer)$'),  # certs / private keys
    re.compile(r'\.github[/\\]workflows[/\\]'),    # CI/CD
    re.compile(r'docker-compose'),                 # docker compose files
    re.compile(r'(^|[/\\])secrets?\.(json|ya?ml|toml)$'),
]


def is_sensitive_file(path: str) -> bool:
    """Return True if the file path matches a high-signal sensitive pattern."""
    name = path.replace("\\", "/").split("/")[-1]
    if name in _SENSITIVE_EXACT:
        return True
    return any(p.search(path) for p in _SENSITIVE_PATTERNS)


# ---------------------------------------------------------------------------
# Anomaly detection
# ---------------------------------------------------------------------------

def compute_anomalies(
    session: dict,
    file_touches: list[dict],
    risky_commands: list[dict],
) -> list[dict]:
    """
    Return detected anomalies as a list of dicts, each with:
        id        str   machine identifier
        label     str   short human label
        detail    str   one-line explanation or evidence
        severity  str   "major" | "minor" | "caution"

    Ordered: major first, then minor, then caution.
    Risky commands are NOT included — the verdict engine reads them separately.

    Severity taxonomy:
        major   — tests_failed, dirty_tree, sensitive_files, low_survival
        minor   — no_commits, file_churn, large_diff
        caution — no_tests  (informational; never affects verdict)
    """
    results: list[dict] = []

    def add(id_: str, label: str, detail: str, severity: str) -> None:
        results.append({"id": id_, "label": label, "detail": detail, "severity": severity})

    # ── major ────────────────────────────────────────────────────────────────

    if session.get("test_outcome") == "fail":
        source = session.get("test_source") or "test runner"
        add("tests_failed", "Tests failed",
            f"Test suite failed at session end ({source})", "major")

    if session.get("tree_dirty"):
        add("dirty_tree", "Uncommitted changes at end",
            "Working directory was not clean when the session ended", "major")

    if session.get("sensitive_files_touched"):
        matched = [t["file_path"] for t in file_touches if is_sensitive_file(t["file_path"])]
        detail = " · ".join(matched[:5])
        if len(matched) > 5:
            detail += f" and {len(matched) - 5} more"
        add("sensitive_files", "Config or env files modified", detail or "sensitive file detected", "major")

    persistence_rate = session.get("persistence_rate")
    persistence_reliable = bool(session.get("persistence_reliable"))
    if persistence_reliable and persistence_rate is not None and persistence_rate < 0.5:
        pct_val = int(round(persistence_rate * 100))
        add("low_survival", "Most edits were reverted",
            f"Only {pct_val}% of touched files survived to git", "major")

    # ── minor ────────────────────────────────────────────────────────────────

    commits_during = session.get("commits_during")
    if session.get("ended_at") is not None and commits_during is not None and commits_during == 0:
        add("no_commits", "No commits made",
            "Claude made no git commits during this session", "minor")

    hot_files = int(session.get("hot_files") or 0)
    if hot_files > 0:
        hot_paths = [t["file_path"] for t in file_touches if t.get("touch_count", 0) >= 3]
        detail = " · ".join(hot_paths[:3])
        if hot_files > 3:
            detail += f" and {hot_files - 3} more"
        add("file_churn", "Files edited repeatedly",
            detail or f"{hot_files} file{'s' if hot_files != 1 else ''} touched 3+ times",
            "minor")

    diff_lines = session.get("diff_lines")
    if diff_lines is not None and diff_lines > 500:
        add("large_diff", "Unusually large changeset",
            f"{diff_lines:,} lines changed — review carefully", "minor")

    # ── caution ──────────────────────────────────────────────────────────────

    if session.get("test_outcome") is None and session.get("ended_at") is not None:
        add("no_tests", "No test signal detected",
            "No test runner output found for this session", "caution")

    return results


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------

def compute_verdict(
    catastrophic_count: int,
    risky_count: int,
    anomalies: list[dict],
) -> str:
    """
    Derive a trust verdict from command flags and anomaly list.
    Evaluated top-down; first match wins.

    Returns one of:
        "blocked" | "high_risk" | "review_required" |
        "trusted_with_caveats" | "trusted"

    Verdict rules (quality_score is NOT used):
        blocked               — any catastrophic command fired
        high_risk             — risky command + at least 1 major anomaly
                                OR 3+ major anomalies (no risky command needed)
        review_required       — any risky command OR 2+ major anomalies
        trusted_with_caveats  — 1 major OR any minor anomaly
        trusted               — all clear (caution-only does not affect verdict)
    """
    if catastrophic_count > 0:
        return "blocked"

    major = sum(1 for a in anomalies if a["severity"] == "major")
    minor = sum(1 for a in anomalies if a["severity"] == "minor")

    if (risky_count > 0 and major >= 1) or major >= 3:
        return "high_risk"
    if risky_count > 0 or major >= 2:
        return "review_required"
    if major >= 1 or minor >= 1:
        return "trusted_with_caveats"
    return "trusted"


def compute_all(session: dict) -> dict:
    """
    Compute all scores from a session row dict (as returned by db.get_session).
    Returns a dict of fields ready to be written back to the DB.

    Handles None / missing values from partially-completed sessions.
    """
    files_touched   = int(session.get("files_touched") or 0)
    hot_files       = int(session.get("hot_files") or 0)
    commits_during  = int(session.get("commits_during") or 0)
    tree_dirty      = bool(session.get("tree_dirty"))         # stored as 0/1
    test_outcome    = session.get("test_outcome")             # 'pass'|'fail'|None
    persistence_rate     = session.get("persistence_rate")    # float|None
    persistence_reliable = bool(session.get("persistence_reliable"))  # stored as 0/1

    wandering = compute_wandering_score(files_touched, hot_files)
    outcome   = compute_outcome_score(
        commits_during, tree_dirty, test_outcome,
        persistence_rate, persistence_reliable,
    )
    quality   = compute_quality_score(outcome, wandering, persistence_rate, persistence_reliable)
    label     = classify_outcome(outcome)

    return {
        "wandering_score": wandering,
        "outcome_score":   outcome,
        "quality_score":   quality,
        "auto_outcome":    label,
    }
