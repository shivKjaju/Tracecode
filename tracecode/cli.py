"""
cli.py — Click command group and all CLI entrypoints.

Day 1: `tracecode init` is fully implemented.
All other commands are stubs that print a message — they will be
filled in on Days 2–6 as each module is built.

Usage:
    tracecode init               # set up ~/.tracecode directory
    tracecode session-start ...  # called by wrapper (Day 2)
    tracecode session-end ...    # called by wrapper (Day 2)
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
    click.echo()
    click.echo("Next steps:")
    click.echo("  1. Install the wrapper script (Day 2 task):")
    click.echo("       cp scripts/claude.wrapper.sh ~/.tracecode/bin/claude")
    click.echo("       chmod +x ~/.tracecode/bin/claude")
    click.echo("  2. Add the wrapper to your PATH:")
    click.echo('       export PATH="$HOME/.tracecode/bin:$PATH"')
    click.echo("       (Add that line to your ~/.zshrc or ~/.bashrc)")
    click.echo("  3. Start a Claude Code session and it will be captured automatically.")


# ---------------------------------------------------------------------------
# tracecode session-start  (stub — implemented Day 2)
# ---------------------------------------------------------------------------

@cli.command("session-start")
@click.option("--project", required=True, help="Absolute path to the project directory")
@click.option("--branch", default="", help="Current git branch")
@click.option("--commit", default="", help="Current HEAD commit SHA")
def cmd_session_start(project: str, branch: str, commit: str) -> None:
    """
    Start a new session. Prints the session UUID to stdout.
    Called by the wrapper script before launching claude.
    """
    # Stub: will be implemented in Day 2 (capture/session.py)
    click.echo("session-start: not yet implemented", err=True)
    sys.exit(1)


# ---------------------------------------------------------------------------
# tracecode session-end  (stub — implemented Day 2)
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
    # Stub: will be implemented in Day 2 (capture/session.py)
    click.echo("session-end: not yet implemented", err=True)
    sys.exit(1)


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
    # Stub: will be implemented in Day 3 (capture/watcher.py)
    click.echo("watch: not yet implemented", err=True)
    sys.exit(1)


# ---------------------------------------------------------------------------
# tracecode serve  (stub — implemented Day 6)
# ---------------------------------------------------------------------------

@cli.command("serve")
@click.option("--port", default=None, type=int, help="Override port from config")
@click.option("--daemon", is_flag=True, help="Run in the background")
def cmd_serve(port: int | None, daemon: bool) -> None:
    """
    Start the Tracecode API and UI server on localhost.
    Serves the REST API at /api/* and the React SPA at /*.
    """
    # Stub: will be implemented in Day 6 (api/main.py)
    click.echo("serve: not yet implemented", err=True)
    sys.exit(1)
