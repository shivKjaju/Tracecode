"""
output/summary.py — Terminal session summary renderer.

Pure function — no I/O, no DB access, no side effects.
Input is plain Python dicts (already computed by the pipeline).
Output is a formatted string ready to print.

Called from two places:
  - cmd_session_end in cli.py      → mode "summary" (brief, stderr)
  - cmd_review in cli.py           → mode "summary" or "full" (stdout)
  - pre-commit hook (via review)   → mode "compact" (single line, stdout)

Rendering modes:
  compact  One line. Used by the pre-commit hook via tracecode review --compact.
  summary  Up to ~10 lines. Used at session-end and by tracecode review (default).
  full     Expanded output with all anomalies and up to 5 review files.
           Used by tracecode review when explicitly invoked by the developer.
"""

import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Verdict label mapping
# ---------------------------------------------------------------------------

_VERDICT_LABELS: dict[str, str] = {
    "trusted":              "Trusted",
    "trusted_with_caveats": "Trusted with caveats",
    "review_required":      "Verify Output",
    "high_risk":            "High-Risk Session",
    "blocked":              "Blocked",
}

# ---------------------------------------------------------------------------
# Reason label mapping
#
# Internal keys (produced by compute_review_first in scoring.py) → display text.
# The internal keys are intentionally not changed in scoring.py so existing
# tests are not broken. The display mapping lives here.
# ---------------------------------------------------------------------------

_REASON_LABELS: dict[str, str] = {
    "protected path":     "protected path",
    "config-sensitive":   "config file",
    "repeated edits":     "repeated edits",
    "unstable edits":     "most edits discarded",
    "in flagged command": "flagged command",
    "flagged command":    "flagged command",
    "in final diff":      "in final diff",
    "persisted":          "persisted",   # suppressed in terminal brief view
}

# These reasons are suppressed in the brief/compact terminal view because they
# are either implied by the file being listed ("persisted") or are too granular
# for a one-line summary ("in final diff" — the reviewer can see this themselves).
# Both are shown in full mode (tracecode review).
_SUPPRESS_IN_TERMINAL: frozenset[str] = frozenset({"persisted", "in final diff"})

# ---------------------------------------------------------------------------
# ANSI color helpers
# ---------------------------------------------------------------------------

_RED    = "\033[31m"
_YELLOW = "\033[33m"
_GREEN  = "\033[32m"
_DIM    = "\033[2m"
_RESET  = "\033[0m"


def _colored(text: str, code: str, use_color: bool) -> str:
    return f"{code}{text}{_RESET}" if use_color else text


def _dim(text: str, use_color: bool) -> str:
    return _colored(text, _DIM, use_color)


def _verdict_color(verdict: str, label: str, use_color: bool) -> str:
    if not use_color:
        return label
    if verdict in ("blocked", "high_risk"):
        return _colored(label, _RED, use_color)
    if verdict in ("review_required", "trusted_with_caveats"):
        return _colored(label, _YELLOW, use_color)
    return _colored(label, _GREEN, use_color)


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _format_duration(started_at: int | None, ended_at: int | None) -> str:
    """Return a human-readable duration string, e.g. '2m 34s'."""
    if not started_at or not ended_at:
        return ""
    seconds = max(0, ended_at - started_at)
    if seconds < 60:
        return f"{seconds}s"
    m, s = divmod(seconds, 60)
    if m < 60:
        return f"{m}m {s:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h {m:02d}m"


def _format_reasons(reasons: list[str], terminal: bool, max_count: int = 2) -> str:
    """Format reason keys into a human-readable inline string."""
    labels = []
    for r in reasons:
        if terminal and r in _SUPPRESS_IN_TERMINAL:
            continue
        labels.append(_REASON_LABELS.get(r, r))
    return " · ".join(labels[:max_count])


def _truncate_path(path: str, max_len: int = 45) -> str:
    """Truncate a long file path with a leading ellipsis."""
    if len(path) <= max_len:
        return path
    return "\u2026" + path[-(max_len - 1):]


# ---------------------------------------------------------------------------
# Main renderer
# ---------------------------------------------------------------------------

def render_session_summary(
    session: dict,
    anomalies: list[dict],
    review_first: list[dict],
    risk_counts: dict,
    compact: bool = False,
    full: bool = False,
    use_color: bool | None = None,
) -> str:
    """
    Render a terminal session summary.

    Parameters:
        session      Full session row dict from the DB.
        anomalies    Output of compute_anomalies().
        review_first Output of compute_review_first().
        risk_counts  Output of count_risky_commands(): {'risky': n, 'catastrophic': n}.
        compact      Return a single-line summary (for the pre-commit hook).
        full         Return the expanded view (for 'tracecode review').
        use_color    Auto-detected from stderr.isatty() when None.

    Returns a formatted string. Never raises.
    """
    if use_color is None:
        # Session-end writes to stderr; review command writes to stdout.
        # Detect based on which stream the caller will use.
        use_color = sys.stderr.isatty()

    verdict        = session.get("verdict") or "trusted"
    session_id     = (session.get("id") or "")[:8]
    project        = session.get("project_name") or ""
    duration       = _format_duration(session.get("started_at"), session.get("ended_at"))
    verdict_label  = _VERDICT_LABELS.get(verdict, verdict)
    verdict_str    = _verdict_color(verdict, verdict_label, use_color)

    risky_count        = int(risk_counts.get("risky", 0))
    catastrophic_count = int(risk_counts.get("catastrophic", 0))
    total_risky        = risky_count + catastrophic_count

    # Split anomalies by category. Anomalies without a category field (e.g.
    # from tests or old data) default to "output" so they surface prominently.
    output_anomalies  = [a for a in anomalies if a.get("category", "output") == "output"]
    process_anomalies = [a for a in anomalies if a.get("category", "output") == "process"]

    output_major   = [a for a in output_anomalies  if a.get("severity") == "major"]
    output_minor   = [a for a in output_anomalies  if a.get("severity") == "minor"]
    output_caution = [a for a in output_anomalies  if a.get("severity") == "caution"]
    process_major  = [a for a in process_anomalies if a.get("severity") == "major"]
    process_minor  = [a for a in process_anomalies if a.get("severity") == "minor"]

    # Flat severity lists still needed for compact mode and trusted-with-caveats logic.
    major_anomalies   = [a for a in anomalies if a.get("severity") == "major"]
    minor_anomalies   = [a for a in anomalies if a.get("severity") == "minor"]
    caution_anomalies = [a for a in anomalies if a.get("severity") == "caution"]

    # ------------------------------------------------------------------ #
    # compact — single line (for pre-commit hook)
    # ------------------------------------------------------------------ #
    if compact:
        parts = [f" tracecode \u203a {session_id} \u00b7 {project}   {verdict_str}"]
        if review_first:
            top   = review_first[0]
            fname = Path(top["file_path"]).name
            parts.append(f"review {fname} first")
        elif major_anomalies:
            parts.append(major_anomalies[0]["label"].lower())
        return "  \u00b7  ".join(parts)

    # ------------------------------------------------------------------ #
    # Header (shared by summary and full modes)
    # ------------------------------------------------------------------ #
    prefix = _dim("tracecode \u203a", use_color)
    header_parts = [f" {prefix} {session_id}"]
    if project:
        header_parts.append(project)
    if duration:
        header_parts.append(duration)
    header = " \u00b7 ".join(header_parts)

    # ------------------------------------------------------------------ #
    # trusted — single line only, nothing more needed
    # ------------------------------------------------------------------ #
    if verdict == "trusted":
        return f"{header}   {verdict_str}"

    # ------------------------------------------------------------------ #
    # All other verdicts — multi-line block
    # ------------------------------------------------------------------ #
    lines: list[str] = ["", header, ""]

    # Verdict
    lines.append(f"   verdict   {verdict_str}")

    # Output line — risky/catastrophic commands + output anomalies.
    # These are signals about what the AI actually left behind.
    output_visible: list[str] = []
    if catastrophic_count:
        s = "s" if catastrophic_count > 1 else ""
        output_visible.append(f"{catastrophic_count} catastrophic command{s} blocked")
    elif total_risky:
        s = "s" if total_risky > 1 else ""
        output_visible.append(f"{total_risky} risky command{s}")

    if output_major:
        output_visible.append(output_major[0]["label"].lower())
    elif verdict == "trusted_with_caveats" and output_minor:
        # Surface the minor output anomaly so caveat sessions are never silent.
        output_visible.append(output_minor[0]["label"].lower())

    if output_visible:
        lines.append(f"   output    {' \u00b7 '.join(output_visible[:2])}")

    # Session line — process anomalies.
    # These describe how the session went, not necessarily the output quality.
    process_visible = process_major + process_minor
    if not process_visible and verdict == "trusted_with_caveats" and not output_visible:
        # Edge case: caveat session with only process-category minor anomalies
        # but anomalies had no category field (e.g. from tests). Fall back to
        # showing the first minor anomaly so the summary is never empty.
        process_visible = minor_anomalies[:1]
    if process_visible:
        process_labels = [a["label"].lower() for a in process_visible[:2]]
        lines.append(f"   session   {' \u00b7 '.join(process_labels)}")

    # Review first section
    if full:
        # Full mode: show any priority, up to 5 files
        files_to_show = review_first[:5]
    else:
        # Summary mode: HIGH priority only (score >= 50) — strong signals only
        files_to_show = [rf for rf in review_first if rf.get("priority") == "HIGH"][:2]
        if not files_to_show and verdict == "trusted_with_caveats" and review_first:
            # Preference from sprint spec: for caveat sessions, surface the top
            # file even if it only reached MEDIUM priority, so the summary is
            # never empty for a session the developer should at least glance at.
            files_to_show = review_first[:1]

    if files_to_show:
        lines.append("")
        for i, rf in enumerate(files_to_show):
            fp         = _truncate_path(rf.get("file_path", ""))
            reasons    = rf.get("reasons", [])
            reason_str = _format_reasons(reasons, terminal=(not full))
            label      = f"{fp}   {reason_str}" if reason_str else fp
            pad        = "   review    " if i == 0 else "             "
            lines.append(f"{pad}{label}")

    # Full mode: show anomalies in two sections — output flags and session noise.
    # output flags = what the AI left behind (trust signals about the output).
    # session noise = how the session went (process quality signals).
    if full:
        if output_major or output_minor or output_caution:
            lines.append("")
            lines.append("   output flags")
            for a in output_major:
                lines.append(f"     \u2717  {a['label']}")
            for a in output_minor:
                lines.append(f"     !  {a['label']}")
            for a in output_caution:
                lines.append(f"     \u00b7  {a['label']}")

        if process_major or process_minor:
            lines.append("")
            lines.append("   session noise")
            for a in process_major:
                lines.append(f"     \u2717  {a['label']}")
            for a in process_minor:
                lines.append(f"     !  {a['label']}")

    # Footer
    lines.append("")
    if full:
        lines.append(f"   {_dim('tracecode serve  to open full session view', use_color)}")
    else:
        lines.append(f"   {_dim('tracecode review  for full details', use_color)}")
    lines.append("")

    return "\n".join(lines)
