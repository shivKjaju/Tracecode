#!/usr/bin/env bash
# ~/.tracecode/bin/claude
#
# Tracecode wrapper for the `claude` CLI.
# Intercepts Claude Code sessions to capture session boundaries, git state,
# and (from Day 3) filesystem changes.
#
# Installation (run once after `tracecode init`):
#   cp scripts/claude.wrapper.sh ~/.tracecode/bin/claude
#   chmod +x ~/.tracecode/bin/claude
#   # Then add to your shell rc:
#   export PATH="$HOME/.tracecode/bin:$PATH"
#
# To point at a specific claude binary:
#   export TRACECODE_CLAUDE_BIN="/usr/local/bin/claude"

set -uo pipefail

# ---------------------------------------------------------------------------
# Find the real claude binary (not this wrapper)
# ---------------------------------------------------------------------------

find_claude() {
    # 1. Explicit override via env var
    if [[ -n "${TRACECODE_CLAUDE_BIN:-}" ]]; then
        echo "$TRACECODE_CLAUDE_BIN"
        return 0
    fi

    # 2. Check common install locations
    local candidates=(
        "/usr/local/bin/claude"
        "$HOME/.claude/local/claude"
        "/opt/homebrew/bin/claude"
    )
    for candidate in "${candidates[@]}"; do
        if [[ -x "$candidate" ]]; then
            echo "$candidate"
            return 0
        fi
    done

    # 3. Search PATH, skipping ~/.tracecode/bin to avoid finding ourselves
    local real
    real=$(
        echo "$PATH" \
        | tr ':' '\n' \
        | grep -v "$HOME/.tracecode/bin" \
        | while read -r dir; do
            if [[ -x "$dir/claude" ]]; then
                echo "$dir/claude"
                break
            fi
        done
    )
    if [[ -n "$real" ]]; then
        echo "$real"
        return 0
    fi

    return 1
}

REAL_CLAUDE=$(find_claude) || {
    echo "tracecode: cannot find the claude binary." >&2
    echo "  Set TRACECODE_CLAUDE_BIN to its full path, e.g.:" >&2
    echo "    export TRACECODE_CLAUDE_BIN=\"/usr/local/bin/claude\"" >&2
    exit 1
}

# ---------------------------------------------------------------------------
# Capture git context for the session
# ---------------------------------------------------------------------------

PROJECT_PATH=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
GIT_BRANCH=$(git branch --show-current 2>/dev/null || echo "")
GIT_COMMIT=$(git rev-parse HEAD 2>/dev/null || echo "")

# ---------------------------------------------------------------------------
# Start session — captures UUID for all subsequent commands
# ---------------------------------------------------------------------------

SESSION_ID=$(tracecode session-start \
    --project "$PROJECT_PATH" \
    --branch  "$GIT_BRANCH" \
    --commit  "$GIT_COMMIT") || {
    # session-start failed — run claude untracked rather than blocking the developer
    echo "tracecode: session-start failed, running claude without tracking." >&2
    exec "$REAL_CLAUDE" "$@"
}

# ---------------------------------------------------------------------------
# Start filesystem watcher as a background process (Days 3+)
# The watcher stub exits immediately until Day 3 — that's fine.
# ---------------------------------------------------------------------------

tracecode watch \
    --session-id "$SESSION_ID" \
    --path       "$PROJECT_PATH" \
    2>/dev/null &
WATCHER_PID=$!
echo "$WATCHER_PID" > "$HOME/.tracecode/watcher_${SESSION_ID}.pid"

# ---------------------------------------------------------------------------
# Run the real claude
#
# Not exec'd — we stay alive to run post-session hooks.
# Bash passes stdin/stdout/stderr and the TTY through to the child process,
# so all of Claude Code's interactive behaviour works normally.
# ---------------------------------------------------------------------------

"$REAL_CLAUDE" "$@"
CLAUDE_EXIT=$?

# ---------------------------------------------------------------------------
# Post-session pipeline (grows each day as new modules are added)
# ---------------------------------------------------------------------------

tracecode session-end \
    --session-id    "$SESSION_ID" \
    --exit-code     "$CLAUDE_EXIT" \
    --project       "$PROJECT_PATH" \
    --commit-before "$GIT_COMMIT" \
    2>&1 | grep -v "^$" >&2 || true  # surface errors to stderr, never fail

# Exit with claude's original exit code so callers see the right status
exit $CLAUDE_EXIT
