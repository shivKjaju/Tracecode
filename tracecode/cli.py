"""
cli.py — Click command group and all CLI entrypoints.

Day 1: `tracecode init` fully implemented.
Day 2: `tracecode session-start` and `tracecode session-end` implemented.
Days 3–6: remaining stubs will be filled in as each module is built.

Usage:
    tracecode init               # set up ~/.tracecode directory
    tracecode session-start ...  # called by wrapper before claude launches
    tracecode session-end ...    # called by wrapper after claude exits
    tracecode watch ...          # filesystem watcher process (Day 3)
    tracecode serve              # API + UI server (Day 6)
"""

import sys
import click
from pathlib import Path

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
    """Tracecode — personal AI coding session quality engine."""
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
@click.option("--project", default="", help="Project directory path (reserved for future use)")
@click.option("--commit-before", default="", help="Git commit SHA at session start (reserved for future use)")
def cmd_session_end(
    session_id: str, exit_code: int, project: str, commit_before: str
) -> None:
    """
    End a session and run the post-session analysis pipeline.
    Called by the wrapper script after claude exits.

    Day 2: records ended_at and exit code only.
    Days 3–5 will add watcher aggregation, git analysis, test detection, and scoring.
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
        click.echo(f"tracecode: session {session_id[:8]} recorded.", err=True)
    except Exception as exc:
        # Never let a session-end failure surface as an error to the developer —
        # their claude session already ended successfully.
        click.echo(f"tracecode session-end error: {exc}", err=True)


# ---------------------------------------------------------------------------
# tracecode watch  (stub — implemented Day 3)
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
# tracecode serve  (stub — implemented Day 6)
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
