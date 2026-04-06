"""
cli.py — Click command group and all CLI entrypoints.

Commands:
    tracecode init               set up ~/.tracecode directory
    tracecode doctor             verify installation health
    tracecode session-start ...  called by wrapper before claude launches
    tracecode session-end ...    called by wrapper after claude exits
    tracecode watch ...          filesystem watcher (background process)
    tracecode guard              PreToolUse hook — blocks dangerous commands
    tracecode checkpoint         PostToolUse hook — surfaces live alerts
    tracecode install-guard      register hooks in ~/.claude/settings.json
    tracecode review [SESSION]   print trust summary for a session
    tracecode install-hook       install pre-commit trust check in a git repo
    tracecode serve              start the API and UI server
"""

import subprocess
import sys
from pathlib import Path

import click

from tracecode.config import (
    DEFAULT_CONFIG_PATH,
    TRACECODE_DIR,
    load_config,
    write_default_config,
)
from tracecode.db import init_db


# ---------------------------------------------------------------------------
# Root group
# ---------------------------------------------------------------------------

@click.group()
@click.version_option(package_name="tracecode")
def cli() -> None:
    """Tracecode — watches Claude Code sessions and tells you what to trust, review, or look at first."""
    pass


# ---------------------------------------------------------------------------
# tracecode init
# ---------------------------------------------------------------------------

@cli.command("init")
def cmd_init() -> None:
    """
    Initialize the ~/.tracecode directory.

    Creates:
      ~/.tracecode/                  (directory)
      ~/.tracecode/config.toml       (default config, only if missing)
      ~/.tracecode/tracecode.db      (SQLite database)
      ~/.tracecode/bin/              (directory for wrapper scripts)
    """
    # 1. Create directories
    TRACECODE_DIR.mkdir(parents=True, exist_ok=True)
    (TRACECODE_DIR / "bin").mkdir(exist_ok=True)
    click.echo(f"  Directory : {TRACECODE_DIR}")

    # 2. Write default config (skips if already exists)
    if DEFAULT_CONFIG_PATH.exists():
        click.echo(f"  Config    : {DEFAULT_CONFIG_PATH} (already exists, not overwritten)")
    else:
        write_default_config(DEFAULT_CONFIG_PATH)
        click.echo(f"  Config    : {DEFAULT_CONFIG_PATH} (created)")

    # 3. Load config so we know the db_path (user may have customized it)
    config = load_config(DEFAULT_CONFIG_PATH)

    # 4. Initialize database
    init_db(config.db_path)
    click.echo(f"  Database  : {config.db_path}")

    click.echo()
    click.echo("Tracecode initialized.")


# ---------------------------------------------------------------------------
# tracecode session-start
# ---------------------------------------------------------------------------

@cli.command("session-start")
@click.option("--project", required=True, help="Absolute path to the project directory")
@click.option("--branch", default="", help="Current git branch")
@click.option("--commit", default="", help="Current HEAD commit SHA")
def cmd_session_start(project: str, branch: str, commit: str) -> None:
    """
    Start a new session. Prints ONLY the session UUID to stdout.
    Called by the wrapper script; the UUID is captured via command substitution.

    Any errors are written to stderr so they don't corrupt the UUID capture.
    """
    from tracecode.capture.session import start_session

    try:
        config = load_config(DEFAULT_CONFIG_PATH)
        session_id = start_session(
            project_path=project,
            git_branch=branch or None,
            git_commit=commit or None,
            config=config,
        )
        # Print UUID only — no trailing message, no newline issues.
        # The wrapper does: SESSION_ID=$(tracecode session-start ...)
        click.echo(session_id)
    except Exception as exc:
        click.echo(f"tracecode session-start error: {exc}", err=True)
        sys.exit(1)


# ---------------------------------------------------------------------------
# tracecode session-end
# ---------------------------------------------------------------------------

@cli.command("session-end")
@click.option("--session-id", required=True, help="UUID returned by session-start")
@click.option("--exit-code", type=int, default=0, help="Exit code of the claude process")
@click.option("--project", default="", help="Project directory path")
@click.option("--commit-before", default="", help="Git commit SHA at session start")
def cmd_session_end(
    session_id: str, exit_code: int, project: str, commit_before: str
) -> None:
    """
    End a session and run the post-session analysis pipeline.
    Called by the wrapper script after claude exits.
    """
    from tracecode.capture.session import end_session

    try:
        config = load_config(DEFAULT_CONFIG_PATH)
        end_session(
            session_id=session_id,
            exit_code=exit_code,
            config=config,
            project_path=project or None,
            git_commit_before=commit_before or None,
        )
    except Exception as exc:
        # Never let a session-end failure surface as an error to the developer —
        # their claude session already ended successfully.
        click.echo(f"tracecode session-end error: {exc}", err=True)
        return

    # Print trust summary to stderr.
    # Re-query the fully-written session row and re-compute the display signals.
    # All data was already computed by the pipeline above; this is just a read
    # plus two deterministic pure-function calls — adds < 10ms.
    try:
        from tracecode.analysis.scoring import compute_anomalies, compute_review_first
        from tracecode.db import (
            get_conn,
            get_file_touches,
            get_risky_commands,
            get_session,
            count_risky_commands,
        )
        from tracecode.output.summary import render_session_summary

        with get_conn(config.db_path) as conn:
            session_row = get_session(conn, session_id) or {}
            touches     = get_file_touches(conn, session_id)
            risks       = get_risky_commands(conn, session_id)
            risk_counts = count_risky_commands(conn, session_id)

        if session_row:
            anomalies    = compute_anomalies(session_row, touches, risks)
            review_first = compute_review_first(
                touches, risks,
                session_row.get("verdict"),
                session_row.get("diff_lines"),
            )
            summary = render_session_summary(
                session=session_row,
                anomalies=anomalies,
                review_first=review_first,
                risk_counts=risk_counts,
            )
            click.echo(summary, err=True)

    except Exception as exc:
        # Summary render failure is non-fatal — fall back to the minimal line
        click.echo(f" tracecode › session {session_id[:8]} recorded.", err=True)


# ---------------------------------------------------------------------------
# tracecode watch
# ---------------------------------------------------------------------------

@cli.command("watch")
@click.option("--session-id", required=True, help="Session UUID to associate events with")
@click.option("--path", required=True, help="Project directory to watch")
def cmd_watch(session_id: str, path: str) -> None:
    """
    Run the filesystem watcher for a session.
    Launched as a background process by the wrapper script.
    Writes file change events to ~/.tracecode/watch_<session_id>.jsonl.
    Runs until it receives SIGTERM.
    """
    from tracecode.capture.watcher import run_watcher
    config = load_config(DEFAULT_CONFIG_PATH)
    run_watcher(session_id, path, config.tracecode_dir)


# ---------------------------------------------------------------------------
# tracecode guard  (PreToolUse hook for Claude Code)
# ---------------------------------------------------------------------------

@cli.command("guard")
def cmd_guard() -> None:
    """
    Claude Code PreToolUse hook — blocks dangerous bash commands.
    Reads tool-use event from stdin (JSON), exits 2 to block or 0 to allow.
    Install with: tracecode install-guard
    """
    from tracecode.guard import run
    run()


@cli.command("checkpoint")
def cmd_checkpoint() -> None:
    """
    Claude Code PostToolUse hook — surfaces runtime checkpoint events to Claude.
    Reads unnotified session_events, prints warnings to stdout, marks as notified.
    Install with: tracecode install-guard
    """
    from tracecode.checkpoint import run
    run()


@cli.command("doctor")
def cmd_doctor() -> None:
    """Check that Tracecode is correctly installed and active."""
    from tracecode.doctor import run_checks

    checks = run_checks()
    failed = [c for c in checks if not c.passed]

    click.echo()
    for c in checks:
        icon = "✓" if c.passed else "✗"
        label_col = f"{c.label:<20}"
        line = f"  {icon}  {label_col} {c.detail}"
        if c.passed:
            click.echo(line)
        else:
            click.echo(click.style(line, fg="red"))

    click.echo()

    if not failed:
        click.echo(click.style("  All checks passed. Tracecode is active.", fg="green"))
        click.echo()
        click.echo("  Next step: run claude in any project, then open Tracecode to review the session.")
        click.echo("    tracecode serve")
        click.echo()
        sys.exit(0)

    # Group hints by unique hint text so identical fixes print once
    hints_seen: set[str] = set()
    for c in failed:
        if c.hint and c.hint not in hints_seen:
            hints_seen.add(c.hint)
            click.echo(click.style("  Fix:", fg="yellow"))
            for line in c.hint.splitlines():
                click.echo(f"    {line}")
            click.echo()

    n = len(failed)
    click.echo(
        click.style(
            f"  {n} check{'s' if n != 1 else ''} failed."
            "  Run `tracecode doctor` again after fixing.",
            fg="red",
        )
    )
    click.echo()
    sys.exit(1)


@cli.command("install-guard")
def cmd_install_guard() -> None:
    """
    Register the guard as a PreToolUse hook in ~/.claude/settings.json.
    """
    import json as _json
    from pathlib import Path

    settings_path = Path.home() / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)

    if settings_path.exists():
        try:
            settings = _json.loads(settings_path.read_text())
        except _json.JSONDecodeError:
            settings = {}
    else:
        settings = {}

    tracecode_bin = str(Path.home() / ".tracecode" / "venv" / "bin" / "tracecode")
    guard_cmd = tracecode_bin + " guard"
    checkpoint_cmd = tracecode_bin + " checkpoint"

    hooks = settings.setdefault("hooks", {})

    # --- PreToolUse: guard ---
    pre_tool_use = hooks.setdefault("PreToolUse", [])
    guard_installed = any(
        "tracecode" in h.get("command", "") and "guard" in h.get("command", "")
        for entry in pre_tool_use
        if entry.get("matcher") == "Bash"
        for h in entry.get("hooks", [])
    )
    if not guard_installed:
        pre_tool_use.append({"matcher": "Bash", "hooks": [{"type": "command", "command": guard_cmd}]})

    # --- PostToolUse: checkpoint ---
    post_tool_use = hooks.setdefault("PostToolUse", [])
    checkpoint_installed = any(
        "tracecode" in h.get("command", "") and "checkpoint" in h.get("command", "")
        for entry in post_tool_use
        if entry.get("matcher") == "Bash"
        for h in entry.get("hooks", [])
    )
    if not checkpoint_installed:
        post_tool_use.append({"matcher": "Bash", "hooks": [{"type": "command", "command": checkpoint_cmd}]})

    if guard_installed and checkpoint_installed:
        click.echo("Guard and checkpoint already installed in ~/.claude/settings.json")
        return

    settings_path.write_text(_json.dumps(settings, indent=2))
    click.echo(f"Hooks installed in {settings_path}")
    click.echo("  PreToolUse  → tracecode guard (blocks dangerous commands)")
    click.echo("  PostToolUse → tracecode checkpoint (surfaces runtime warnings to Claude)")


# ---------------------------------------------------------------------------
# Shared helper — project path resolution
# ---------------------------------------------------------------------------

def _resolve_project_path(override: str | None) -> str:
    """
    Resolve the current project path for session lookup.

    Priority:
      1. --project override from the caller
      2. Git repository root (git rev-parse --show-toplevel)
      3. Current working directory as fallback

    Returns an absolute path string matching the form stored by start_session().
    """
    if override:
        return str(Path(override).resolve())
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=3,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return str(Path.cwd())


# ---------------------------------------------------------------------------
# tracecode review
# ---------------------------------------------------------------------------

@cli.command("review")
@click.argument("session_id", required=False, default=None,
                metavar="[SESSION_ID]")
@click.option("--last", "use_last", is_flag=True, default=False,
              help="Show most recent ended session for this project (default when no SESSION_ID).")
@click.option("--compact", is_flag=True, default=False,
              help="Single-line output. Used by the pre-commit hook.")
@click.option("--quiet-if-trusted", is_flag=True, default=False,
              help="Print nothing when the session verdict is 'trusted'.")
@click.option("--project", default=None,
              help="Override the project path used for session lookup.")
def cmd_review(
    session_id: str | None,
    use_last: bool,
    compact: bool,
    quiet_if_trusted: bool,
    project: str | None,
) -> None:
    """
    Print the trust summary for a session.

    Defaults to the most recent ended session for the current project.
    Pass a SESSION_ID (full UUID or 8-char prefix) to review a specific session.

    Examples:
      tracecode review               # most recent session, full output
      tracecode review 8a3f1b2c      # specific session by prefix
      tracecode review --compact     # one-line (used by pre-commit hook)
    """
    import time

    from tracecode.analysis.scoring import compute_anomalies, compute_review_first
    from tracecode.db import (
        get_conn,
        get_file_touches,
        get_risky_commands,
        get_session,
        get_session_by_prefix,
        get_latest_session_for_project,
        count_risky_commands,
    )
    from tracecode.output.summary import render_session_summary

    try:
        config = load_config(DEFAULT_CONFIG_PATH)
    except Exception as exc:
        if not compact:
            click.echo(f"  Could not load config: {exc}", err=True)
        sys.exit(1)

    resolved_project = _resolve_project_path(project)

    # ── Locate the session ──────────────────────────────────────────────────
    session_row: dict | None = None
    with get_conn(config.db_path) as conn:
        if session_id:
            # Try exact UUID match first, then 8-char prefix
            session_row = get_session(conn, session_id)
            if not session_row:
                session_row = get_session_by_prefix(conn, session_id)
        else:
            # --last is the default when no SESSION_ID is given
            session_row = get_latest_session_for_project(conn, resolved_project)

    if not session_row:
        if not compact:
            name = Path(resolved_project).name
            click.echo(f"  No sessions found for {name}.")
            click.echo("  Run claude in a project directory to start recording.")
        return

    # ── Guard: session still in progress ────────────────────────────────────
    if not session_row.get("ended_at"):
        if not compact:
            sid = (session_row.get("id") or "")[:8]
            click.echo(f"  Session {sid} is still in progress.")
        return

    # ── Staleness check (compact/hook mode only) ─────────────────────────────
    # In compact mode the command is invoked by the pre-commit hook, which runs
    # immediately after a session. If the last session ended more than 2 hours
    # ago, the developer is committing unrelated work — stay silent.
    if compact:
        ended_at = int(session_row.get("ended_at") or 0)
        if time.time() - ended_at > 7200:
            return

    # ── Quiet-if-trusted ────────────────────────────────────────────────────
    verdict = session_row.get("verdict") or "trusted"
    if quiet_if_trusted and verdict == "trusted":
        return

    # ── Load associated data and render ─────────────────────────────────────
    sid = session_row["id"]
    with get_conn(config.db_path) as conn:
        touches     = get_file_touches(conn, sid)
        risks       = get_risky_commands(conn, sid)
        risk_counts = count_risky_commands(conn, sid)

    anomalies    = compute_anomalies(session_row, touches, risks)
    review_first = compute_review_first(
        touches, risks, verdict, session_row.get("diff_lines")
    )

    # Full mode when the user explicitly invoked the command without --compact
    full = not compact

    summary = render_session_summary(
        session=session_row,
        anomalies=anomalies,
        review_first=review_first,
        risk_counts=risk_counts,
        compact=compact,
        full=full,
        use_color=sys.stdout.isatty(),
    )
    click.echo(summary)


# ---------------------------------------------------------------------------
# tracecode install-hook
# ---------------------------------------------------------------------------

_HOOK_MARKER = "# Installed by: tracecode install-hook"

_HOOK_FULL = """\
#!/usr/bin/env bash
# Tracecode pre-commit trust check — non-blocking, always exits 0.
{marker}
# Remove with: tracecode install-hook --remove
command -v tracecode >/dev/null 2>&1 \\
  && tracecode review --last --compact --quiet-if-trusted 2>/dev/null \\
  || true
""".format(marker=_HOOK_MARKER)

_HOOK_APPEND = """
# ---------------------------------------------------------------------------
# Tracecode pre-commit trust check — non-blocking, always exits 0.
{marker}
# Remove with: tracecode install-hook --remove
command -v tracecode >/dev/null 2>&1 \\
  && tracecode review --last --compact --quiet-if-trusted 2>/dev/null \\
  || true
""".format(marker=_HOOK_MARKER)


@cli.command("install-hook")
@click.option("--project-path", default=None,
              help="Git project root (default: git root of current directory).")
@click.option("--remove", is_flag=True, default=False,
              help="Remove the installed hook.")
def cmd_install_hook(project_path: str | None, remove: bool) -> None:
    """
    Install (or remove) a non-blocking pre-commit trust check.

    After each AI coding session, git commits in this project will show a
    one-line Tracecode trust summary before the commit message prompt.

    The hook always exits 0 — it never blocks a commit.

    Examples:
      tracecode install-hook                # install in current project
      tracecode install-hook --remove       # remove the hook
    """
    resolved = _resolve_project_path(project_path)
    git_dir  = Path(resolved) / ".git"

    if not git_dir.is_dir():
        click.echo(f"  Not a git repository: {resolved}")
        click.echo("  Run this command from inside a project directory.")
        sys.exit(1)

    hook_dir  = git_dir / "hooks"
    hook_dir.mkdir(exist_ok=True)
    hook_path = hook_dir / "pre-commit"

    # ── Remove ──────────────────────────────────────────────────────────────
    if remove:
        if not hook_path.exists():
            click.echo("  No pre-commit hook found.")
            return

        content = hook_path.read_text()
        if _HOOK_MARKER not in content:
            click.echo("  Tracecode hook not found in .git/hooks/pre-commit.")
            click.echo("  Nothing removed.")
            return

        # Check whether the file contains only our hook.
        # Strip shebang, blank lines, and our own lines to see what's left.
        other_lines = [
            line for line in content.splitlines()
            if line.strip()
            and not line.startswith("#")
            and "tracecode" not in line.lower()
            and "#!/usr/bin/env bash" not in line
        ]
        if not other_lines:
            hook_path.unlink()
            click.echo("  Removed pre-commit hook.")
        else:
            click.echo("  The pre-commit hook contains other content.")
            click.echo(f"  Remove the Tracecode block manually from: {hook_path}")
            click.echo(f"  Look for the line: {_HOOK_MARKER}")
        return

    # ── Install ──────────────────────────────────────────────────────────────
    if hook_path.exists():
        content = hook_path.read_text()
        if _HOOK_MARKER in content:
            click.echo("  Tracecode pre-commit hook is already installed.")
            click.echo(f"  Location: {hook_path}")
            return

        # Append our block to the existing hook
        with hook_path.open("a") as f:
            f.write(_HOOK_APPEND)
        click.echo(f"  Appended Tracecode trust check to: {hook_path}")
    else:
        hook_path.write_text(_HOOK_FULL)
        hook_path.chmod(0o755)
        click.echo(f"  Installed pre-commit hook: {hook_path}")

    click.echo()
    click.echo("  After each AI coding session, commits here will show a trust summary.")
    click.echo("  Example:")
    click.echo("   tracecode \u203a 8a3f1b2 \u00b7 myproject   Needs Review  \u00b7  review auth/session.py first")
    click.echo()
    click.echo("  Run 'tracecode review' for the full session detail.")
    click.echo("  Run 'tracecode install-hook --remove' to uninstall.")


# ---------------------------------------------------------------------------
# tracecode serve
# ---------------------------------------------------------------------------

@cli.command("serve")
@click.option("--port", default=None, type=int, help="Override port from config")
@click.option("--host", default="127.0.0.1", help="Host to bind (default: 127.0.0.1)")
def cmd_serve(port: int | None, host: str) -> None:
    """
    Start the Tracecode API and UI server on localhost.
    Serves the REST API at /api/* and the Next.js UI at /*.
    """
    import uvicorn
    from tracecode.api.main import app

    config = load_config(DEFAULT_CONFIG_PATH)
    resolved_port = port or config.server_port

    click.echo(f"Starting Tracecode server at http://{host}:{resolved_port}")
    click.echo(f"API docs: http://{host}:{resolved_port}/api/docs")
    click.echo("Press Ctrl+C to stop.")

    uvicorn.run(
        app,
        host=host,
        port=resolved_port,
        log_level="warning",  # keep output clean; errors still surface
    )
