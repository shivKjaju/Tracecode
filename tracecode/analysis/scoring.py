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
