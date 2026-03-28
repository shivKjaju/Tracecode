#!/usr/bin/env bash
# Tracecode installer
#
# Usage (from repo root):
#   ./scripts/install.sh
#
# Or remotely:
#   curl -fsSL https://raw.githubusercontent.com/shivKjaju/Tracecode/main/scripts/install.sh | bash

set -euo pipefail

TRACECODE_DIR="$HOME/.tracecode"
VENV_DIR="$TRACECODE_DIR/venv"
BIN_DIR="$TRACECODE_DIR/bin"
WRAPPER="$BIN_DIR/claude"

# Resolve repo root — works whether run locally or piped from curl
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." 2>/dev/null && pwd || echo "")"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

green()  { echo -e "\033[32m$*\033[0m"; }
yellow() { echo -e "\033[33m$*\033[0m"; }
red()    { echo -e "\033[31m$*\033[0m"; }
step()   { echo; green "▶ $*"; }

die() {
    red "Error: $*"
    exit 1
}

# ---------------------------------------------------------------------------
# Check Python
# ---------------------------------------------------------------------------

step "Checking Python..."

PYTHON=""
for candidate in python3.12 python3.11 python3; do
    if command -v "$candidate" &>/dev/null; then
        version=$("$candidate" -c "import sys; print(sys.version_info[:2])")
        if "$candidate" -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" 2>/dev/null; then
            PYTHON="$candidate"
            echo "  Found: $("$candidate" --version)"
            break
        fi
    fi
done

[[ -n "$PYTHON" ]] || die "Python 3.11+ is required. Install it from https://python.org or via brew: brew install python@3.12"

# ---------------------------------------------------------------------------
# Find the real claude binary before we install the wrapper
# ---------------------------------------------------------------------------

step "Locating Claude Code binary..."

REAL_CLAUDE=""
for candidate in \
    "/usr/local/bin/claude" \
    "$HOME/.claude/local/claude" \
    "/opt/homebrew/bin/claude"; do
    if [[ -x "$candidate" ]]; then
        REAL_CLAUDE="$candidate"
        echo "  Found: $REAL_CLAUDE"
        break
    fi
done

# Also search PATH (excluding our own bin dir, which may already have the wrapper)
if [[ -z "$REAL_CLAUDE" ]]; then
    REAL_CLAUDE=$(
        echo "$PATH" \
        | tr ':' '\n' \
        | grep -v "$BIN_DIR" \
        | while read -r dir; do
            [[ -x "$dir/claude" ]] && echo "$dir/claude" && break
        done
    )
    [[ -n "$REAL_CLAUDE" ]] && echo "  Found: $REAL_CLAUDE"
fi

if [[ -z "$REAL_CLAUDE" ]]; then
    yellow "  Warning: claude binary not found. Install Claude Code first:"
    yellow "    https://claude.ai/code"
    yellow "  You can still install Tracecode now — it will prompt again on first use."
    REAL_CLAUDE="/usr/local/bin/claude"  # default fallback path
fi

# ---------------------------------------------------------------------------
# Create directories
# ---------------------------------------------------------------------------

step "Creating ~/.tracecode directory..."
mkdir -p "$TRACECODE_DIR" "$BIN_DIR"
echo "  $TRACECODE_DIR"

# ---------------------------------------------------------------------------
# Create venv and install package
# ---------------------------------------------------------------------------

step "Setting up Python environment..."

if [[ ! -d "$VENV_DIR" ]]; then
    "$PYTHON" -m venv "$VENV_DIR"
    echo "  Created venv at $VENV_DIR"
else
    echo "  Venv already exists at $VENV_DIR"
fi

VENV_PIP="$VENV_DIR/bin/pip"
VENV_TRACECODE="$VENV_DIR/bin/tracecode"

# Upgrade pip silently
"$VENV_PIP" install --upgrade pip --quiet

if [[ -n "$REPO_ROOT" && -f "$REPO_ROOT/pyproject.toml" ]]; then
    # Installing from local repo (editable — code changes are picked up instantly)
    echo "  Installing from local repo (editable)..."
    "$VENV_PIP" install -e "$REPO_ROOT" --quiet
else
    # Remote install — install from PyPI (not published yet; placeholder)
    die "Remote install not yet supported. Clone the repo and run ./scripts/install.sh"
fi

echo "  tracecode $("$VENV_TRACECODE" --version | awk '{print $NF}') installed"

# ---------------------------------------------------------------------------
# Build the Next.js UI
# ---------------------------------------------------------------------------

step "Building UI..."

if [[ -n "$REPO_ROOT" && -d "$REPO_ROOT/ui" ]]; then
    if command -v npm &>/dev/null; then
        echo "  npm $(npm --version)"
        echo "  Installing UI dependencies..."
        npm install --prefix "$REPO_ROOT/ui" --silent
        echo "  Building static export..."
        npm run build --prefix "$REPO_ROOT/ui" --silent
        echo "  UI built at $REPO_ROOT/ui/out"
    else
        yellow "  npm not found — skipping UI build."
        yellow "  Install Node.js, then run: cd ui && npm install && npm run build"
        yellow "  Without the UI build, 'tracecode serve' will show a fallback message."
    fi
else
    yellow "  ui/ directory not found — skipping UI build."
fi

# ---------------------------------------------------------------------------
# Initialize ~/.tracecode (config + DB)
# ---------------------------------------------------------------------------

step "Initializing Tracecode..."
"$VENV_TRACECODE" init

step "Installing guard hook..."
"$VENV_TRACECODE" install-guard

# ---------------------------------------------------------------------------
# Write the wrapper script
# ---------------------------------------------------------------------------

step "Installing claude wrapper..."

cat > "$WRAPPER" << WRAPPER_EOF
#!/usr/bin/env bash
# Tracecode wrapper for \`claude\`
# Auto-generated by install.sh — do not edit manually.
# Re-run ./scripts/install.sh to regenerate.

set -uo pipefail

TRACECODE="$VENV_TRACECODE"
REAL_CLAUDE="${TRACECODE_CLAUDE_BIN:-$REAL_CLAUDE}"

# Verify both binaries exist
if [[ ! -x "\$TRACECODE" ]]; then
    echo "tracecode: missing \$TRACECODE — re-run install.sh" >&2
    exec "\$REAL_CLAUDE" "\$@"
fi
if [[ ! -x "\$REAL_CLAUDE" ]]; then
    echo "tracecode: cannot find claude at \$REAL_CLAUDE" >&2
    echo "  Set TRACECODE_CLAUDE_BIN to the full path of your claude binary." >&2
    exit 1
fi

# Capture git context
PROJECT_PATH=\$(git rev-parse --show-toplevel 2>/dev/null || pwd)
GIT_BRANCH=\$(git branch --show-current 2>/dev/null || echo "")
GIT_COMMIT=\$(git rev-parse HEAD 2>/dev/null || echo "")

# Start session
SESSION_ID=\$("\$TRACECODE" session-start \
    --project "\$PROJECT_PATH" \
    --branch  "\$GIT_BRANCH" \
    --commit  "\$GIT_COMMIT") || {
    echo "tracecode: session-start failed, running claude without tracking." >&2
    exec "\$REAL_CLAUDE" "\$@"
}

# Notify user that recording has started
PROJECT_NAME=\$(basename "\$PROJECT_PATH")
SHORT_ID=\${SESSION_ID:0:8}
echo -e "\033[2m tracecode › recording \$SHORT_ID · \$PROJECT_NAME\033[0m" >&2

# Publish session ID so the guard hook can link flagged commands to this session
echo "\$SESSION_ID" > "\$HOME/.tracecode/current_session"

# Start filesystem watcher (Day 3+)
"\$TRACECODE" watch \
    --session-id "\$SESSION_ID" \
    --path       "\$PROJECT_PATH" \
    2>/dev/null &
echo "\$!" > "\$HOME/.tracecode/watcher_\${SESSION_ID}.pid"

# Run real claude — not exec'd so post-session hooks run after it exits
"\$REAL_CLAUDE" "\$@"
CLAUDE_EXIT=\$?

# Clear current session so guard doesn't attach to a stale session
rm -f "\$HOME/.tracecode/current_session"

# Post-session pipeline
"\$TRACECODE" session-end \
    --session-id    "\$SESSION_ID" \
    --exit-code     "\$CLAUDE_EXIT" \
    --project       "\$PROJECT_PATH" \
    --commit-before "\$GIT_COMMIT" \
    2>&1 | grep -v "^$" >&2 || true

exit \$CLAUDE_EXIT
WRAPPER_EOF

chmod +x "$WRAPPER"
echo "  Installed: $WRAPPER"
echo "  Wraps:     $REAL_CLAUDE"

# ---------------------------------------------------------------------------
# Add ~/.tracecode/bin to PATH if not already there
# ---------------------------------------------------------------------------

step "Configuring PATH..."

add_to_path() {
    local rc_file="$1"
    local marker="# added by tracecode installer"
    if [[ -f "$rc_file" ]] && grep -q "tracecode" "$rc_file" 2>/dev/null; then
        echo "  $rc_file already contains PATH entry — skipping"
        return
    fi
    if [[ -f "$rc_file" ]]; then
        echo "" >> "$rc_file"
        echo "$marker" >> "$rc_file"
        echo 'export PATH="$HOME/.tracecode/bin:$PATH"' >> "$rc_file"
        echo "  Added to $rc_file"
    fi
}

ADDED=false
# Detect shell and update appropriate rc file
if [[ "${SHELL:-}" == */zsh ]]; then
    add_to_path "$HOME/.zshrc"
    ADDED=true
fi
if [[ "${SHELL:-}" == */bash ]]; then
    add_to_path "$HOME/.bashrc"
    add_to_path "$HOME/.bash_profile"
    ADDED=true
fi
if [[ "$ADDED" == false ]]; then
    yellow "  Could not detect shell rc file."
    yellow "  Add this line manually to your shell config:"
    yellow '    export PATH="$HOME/.tracecode/bin:$PATH"'
fi

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------

echo
green "✓ Tracecode installed successfully."
echo
echo "  Reload your shell to activate:"
echo "    source ~/.zshrc    # or ~/.bashrc"
echo
echo "  Then just use claude normally:"
echo "    cd your-project"
echo "    claude"
echo
echo "  Sessions are captured automatically. View them at any time:"
echo "    tracecode serve"
echo "    open http://localhost:7842"
echo
