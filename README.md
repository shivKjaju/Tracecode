# Tracecode

Tracecode watches every Claude Code session and tells you what to trust, review, or look at first.

It runs locally, stores nothing remotely, and stays out of the way until something needs your attention.

---

## What it does

When you run `claude`, Tracecode:

- Records which files were edited, how often, and whether they survived to git
- Monitors for dangerous shell commands and blocks the worst ones before they run
- Detects patterns that suggest a session went sideways — repeated edits, uncommitted changes, sensitive file modifications
- Produces a **trust verdict** for each session: Trusted, Needs Review, High Risk, or Blocked
- Ranks the top files worth inspecting first, so you're not guessing where to look

The result is a session feed with verdicts, and a detail page that tells you where to focus.

---

## Key features

- **Trust verdict** — a clear signal on every session: Trusted / Trusted with Caveats / Needs Review / High Risk / Blocked
- **Blocked commands** — catastrophic shell commands (`rm -rf /`, `curl | bash`, disk writes) are intercepted before they run
- **Flagged commands** — risky commands (force-push to main, `DROP TABLE`, `sudo rm`) are logged and surfaced after the session
- **Review First** — the top 3–5 files most worth inspecting, ranked by sensitivity, edit count, git persistence, and involvement in flagged commands
- **Live alerts** — runtime warnings fired during the session when edits spread unusually wide, a file is thrashed, or risky commands accumulate
- **Session feed** — chronological list of sessions with verdicts and key signals at a glance
- **Local-first** — all data lives in `~/.tracecode/tracecode.db`; nothing leaves your machine

---

## How it works

Tracecode has three layers:

### 1. Session capture (wrapper)

A thin shell wrapper replaces `claude` in your PATH. When you run `claude`, the wrapper:

- Records the session start, git branch, and HEAD commit
- Starts a background filesystem watcher
- Runs the real `claude` — you interact with it exactly as before
- After `claude` exits, runs the post-session analysis pipeline

The wrapper is transparent. Your workflow does not change.

### 2. Runtime guardrails (hooks)

Two Claude Code hooks run on every bash tool use:

- **Guard** (PreToolUse) — inspects every shell command before it runs. Blocks catastrophic commands outright. Logs risky commands and allows them — Claude's own permission prompt still fires.
- **Checkpoint** (PostToolUse) — checks for live warning conditions and surfaces them to Claude in-context when thresholds are crossed.

### 3. Post-session analysis

After `claude` exits, the pipeline runs automatically:

1. Aggregates file touch events from the watcher
2. Queries git: commits made, tree cleanliness, net diff
3. Computes what fraction of touched files survived to git
4. Detects test outcome from a configured command or pytest/JUnit artifacts
5. Scores the session and detects issues
6. Computes a trust verdict
7. Writes everything to the local SQLite database

The UI reads from the database. No network required.

---

## Requirements

- macOS or Linux
- Python 3.11+
- Node.js 18+ (for the UI build)
- Claude Code installed

---

## Install

From the repo:

```bash
git clone https://github.com/shivKjaju/Tracecode.git
cd Tracecode
./scripts/install.sh
```

The installer:

1. Creates `~/.tracecode/` and a dedicated Python venv
2. Installs the `tracecode` package
3. Builds the Next.js UI
4. Runs `tracecode init` (config + database)
5. Installs the guard and checkpoint hooks into `~/.claude/settings.json`
6. Installs the `claude` wrapper at `~/.tracecode/bin/claude`
7. Adds `~/.tracecode/bin` to your shell PATH

---

## Setup

After installing, reload your shell:

```bash
source ~/.zshrc    # or ~/.bashrc
```

Verify everything is working:

```bash
tracecode doctor
```

You should see all checks pass. If anything is off, the output tells you exactly what to fix.

---

## Verify setup

```bash
tracecode doctor
```

Expected output when everything is correct:

```
  ✓  directory          ~/.tracecode/
  ✓  wrapper bin dir    ~/.tracecode/bin/
  ✓  config             ~/.tracecode/config.toml
  ✓  database           ~/.tracecode/tracecode.db (0 sessions)
  ✓  claude binary      /usr/local/bin/claude
  ✓  wrapper            ~/.tracecode/bin/claude (active)
  ✓  PATH order         claude → wrapper ✓
  ✓  hooks file         ~/.claude/settings.json
  ✓  guard hook         PreToolUse → tracecode guard
  ✓  checkpoint hook    PostToolUse → tracecode checkpoint

  All checks passed. Tracecode is active.

  Next step: run claude in any project, then open Tracecode to review the session.
    tracecode serve
```

---

## Normal workflow

Just use `claude` as you normally would:

```bash
cd your-project
claude
```

When the session ends, you'll see a brief line from Tracecode on stderr:

```
 tracecode › recording a1b2c3d4 · your-project
```

Open the UI to review the session:

```bash
tracecode serve
```

Navigate to `http://localhost:7842`.

---

## The session feed

Each row shows:

- **Verdict** — the trust verdict for that session
- **Project + branch** — which project and git branch
- **Key signals** — up to two notable issues (e.g. "3 risky commands", "config files modified")
- **Duration + time**

Click any row to open the full session detail.

---

## Trust verdicts

Every completed session gets one of five verdicts:

| Verdict | Meaning | What to do |
|---------|---------|------------|
| **Trusted** | All signals clear. | Safe to continue. No action needed. |
| **Trusted with Caveats** | Minor signals worth a look. | Scan the issues section before closing. |
| **Needs Review** | Risky commands used, or multiple issues found. | Read flagged commands and changed files before continuing. |
| **High Risk** | Multiple serious issues. | Do not merge or deploy until you have reviewed every flagged item. |
| **Blocked** | A catastrophic command was attempted. | Treat outputs as untrusted. Audit every change before use. |

Verdicts are computed from:

- Whether catastrophic or risky commands were used
- Whether tests failed
- Whether the working tree was dirty at session end
- Whether sensitive or config files were modified
- Whether most edits were reverted (low persistence)
- Whether the diff was unusually large

---

## Review First

The detail page shows a **Review First** section: the top 3–5 files most worth inspecting, each with a short reason and priority level.

Files are ranked by a combination of signals:

| Signal | Weight |
|--------|--------|
| Persisted to git | High |
| Config or sensitive file | High |
| Repeated edits (touched 3+ times, saved) | Medium |
| Unstable edits (touched 3+ times, not saved) | Medium |
| Referenced in a flagged command | Medium |
| In the final diff | Low |

Files with no meaningful signal are omitted. The section is suppressed for Trusted sessions with nothing notable.

---

## Runtime guardrails

### Blocked commands

Stopped before they run. Claude sees the block and cannot proceed:

- `rm -rf /` or `rm -rf ~`
- `dd` writing to a disk device
- Fork bombs
- Overwriting `/etc/passwd`, `/etc/shadow`
- `curl ... | sh` or `wget ... | bash`
- Writing to system paths outside the project

### Flagged commands

Logged and allowed. Claude's own permission prompt still fires. Visible in the session detail:

- `sudo rm`
- Force-push to main/master
- `DROP TABLE`, `TRUNCATE TABLE`
- `chmod -R 777`
- `killall`
- `rm -rf` (non-system targets)

### Live alerts

Fired during the session and surfaced to Claude in-context:

- Too many files touched in a short window (blast radius spike)
- A single file edited 5+ times
- 3+ risky commands accumulated

Visible in the session detail as **live alerts**.

---

## Configuration

Tracecode reads `~/.tracecode/config.toml`. Defaults work without changes. Common overrides:

```toml
[tracecode]
server_port = 7842

[test]
# Run after every session to detect pass/fail outcome
command = "pytest -q --tb=no"
timeout_seconds = 30

# Per-project override
[projects]
[projects."/Users/you/myapp"]
test_command = "npm test -- --watchAll=false"
test_timeout = 60
```

---

## Troubleshooting

**Sessions are not being recorded**

Run `tracecode doctor`. Most likely the wrapper is not intercepting `claude`.

```bash
source ~/.zshrc
which claude   # should show ~/.tracecode/bin/claude
```

**Verdict shows "No data" for an old session**

The session may have ended before analysis completed. Open the detail page — the verdict will recompute automatically from available data.

**Guard hook not firing**

```bash
tracecode doctor
tracecode install-guard
```

Restart Claude Code after installing hooks.

**UI will not load**

Make sure `tracecode serve` is running in a terminal. If the UI build is missing:

```bash
cd ui && npm install && npm run build
```

**Want to reinstall cleanly**

```bash
./scripts/install.sh
```

The installer is idempotent — safe to re-run.

---

## What Tracecode does not do

- Does not modify your code
- Does not send data anywhere — everything stays in `~/.tracecode/`
- Does not require an account or API key
- Does not capture terminal output or conversation content — only filesystem events, git state, and shell commands
- Does not integrate with CI, GitHub, Slack, or any external service
- Does not support team or shared sessions — this is a personal tool

---

## Privacy

All session data is stored locally in `~/.tracecode/tracecode.db`. Nothing is transmitted to any server. The UI binds to `127.0.0.1` only.

Tracecode records:

- File paths modified during sessions (not file contents)
- Shell commands matching risky or catastrophic patterns (command string only, truncated to 500 characters)
- Git metadata: branch names, commit SHAs, diff line counts
- Session timing

---

## Current limitations

- macOS and Linux only — Windows is not supported
- Git projects only — file persistence analysis requires git
- Single-machine — no sync across devices
- Test detection works automatically with pytest and JUnit XML; other frameworks require a configured test command
- No push notifications — you open the UI manually after sessions

---

## Developer notes

```bash
# Install in editable mode
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Run tests
pytest

# Run the API server (without UI)
tracecode serve

# Run the UI dev server (hot reload)
cd ui && npm run dev
```

The backend is FastAPI + SQLite, serving a statically-exported Next.js UI. All scoring logic lives in `tracecode/analysis/scoring.py` — pure functions, no I/O, easy to test in isolation.
