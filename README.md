by by  # Tracecode

**Tracecode watches every Claude Code session and tells you what to trust, review, or look at first.**

It runs locally, stores nothing remotely, and stays out of the way until something needs your attention.

![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux-lightgrey)
![License](https://img.shields.io/badge/license-MIT-green)

---

## How it works

```
  you type: claude
       │
       ▼
 ┌─────────────────────────────────────────────────────┐
 │  wrapper (intercepts claude in PATH)                │
 │  · records session start, git branch, HEAD commit   │
 │  · starts background filesystem watcher             │
 └──────────────────────┬──────────────────────────────┘
                        │
                        ▼
 ┌─────────────────────────────────────────────────────┐
 │  Claude Code runs normally — your workflow unchanged│
 │                                                     │
 │  guard hook (PreToolUse)                            │
 │  · blocks catastrophic shell commands before run    │
 │                                                     │
 │  checkpoint hook (PostToolUse)                      │
 │  · fires live alerts to Claude when thresholds hit  │
 └──────────────────────┬──────────────────────────────┘
                        │ session ends
                        ▼
 ┌─────────────────────────────────────────────────────┐
 │  post-session pipeline (automatic)                  │
 │  · aggregates file edits, git diff, test outcome    │
 │  · scores the session                               │
 │  · writes trust verdict to local SQLite DB          │
 └──────────────────────┬──────────────────────────────┘
                        │
                        ▼
              tracecode serve
              → open http://localhost:7842
```

---

## What you get

- **Trust verdict** on every session — Trusted / Trusted with Caveats / Needs Review / High Risk / Blocked
- **Review First** — the top 3–5 files most worth inspecting, ranked automatically
- **Blocked commands** — catastrophic shell commands stopped before they run
- **Session feed** — all sessions in one place, with verdicts and key signals at a glance

---

## Install

```bash
git clone https://github.com/shivKjaju/Tracecode.git
cd Tracecode
./scripts/install.sh
```

Then reload your shell and verify:

```bash
source ~/.zshrc
tracecode doctor
```

Expected output:

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

```bash
cd your-project
claude                  # runs exactly as before

# when the session ends:
tracecode serve         # open http://localhost:7842
```

That's it. You don't change how you use Claude.

---

## Trust verdicts

| Verdict | What it means | What to do |
|---------|---------------|------------|
| **Trusted** | All signals clear | Safe to continue — no action needed |
| **Trusted with Caveats** | Minor signals worth a look | Scan the issues section before closing |
| **Needs Review** | Risky commands used or multiple issues | Read flagged commands and changed files before continuing |
| **High Risk** | Multiple serious signals | Don't merge or deploy until you've reviewed every flagged item |
| **Blocked** | A catastrophic command was attempted | Treat all outputs as untrusted — audit every change before use |

Verdicts are computed from: risky/catastrophic commands, test outcome, dirty working tree, sensitive file edits, low git persistence, and diff size.

---

<details>
<summary><strong>Review First — how files are ranked</strong></summary>

The detail page shows the top 3–5 files most worth inspecting, each with a priority level and short reason.

| Signal | Weight |
|--------|--------|
| Persisted to git | High |
| Config or sensitive file | High |
| Repeated edits (touched 3+ times, saved) | Medium |
| Unstable edits (touched 3+ times, not saved to git) | Medium |
| Referenced in a flagged command | Medium |
| In the final diff | Low |

Files with no meaningful signal are omitted. The section is suppressed for Trusted sessions with nothing notable.

</details>

<details>
<summary><strong>Runtime guardrails — what gets blocked vs flagged</strong></summary>

### Blocked (stopped before they run)

- `rm -rf /` or `rm -rf ~`
- `dd` writing to a disk device
- Fork bombs
- Overwriting `/etc/passwd` or `/etc/shadow`
- `curl ... | sh` or `wget ... | bash`
- Writing to system paths outside the project

### Flagged (logged, allowed — Claude's own permission prompt still fires)

- `sudo rm`
- Force-push to main/master
- `DROP TABLE`, `TRUNCATE TABLE`
- `chmod -R 777`
- `killall`
- `rm -rf` (non-system targets)

### Live alerts (fired in-session, surfaced to Claude in-context)

- Too many files touched in a short window
- A single file edited 5+ times
- 3+ risky commands accumulated

</details>

<details>
<summary><strong>Configuration</strong></summary>

Tracecode reads `~/.tracecode/config.toml`. Defaults work without changes.

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

</details>

<details>
<summary><strong>Troubleshooting</strong></summary>

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

Make sure `tracecode serve` is running. If the UI build is missing:

```bash
cd ui && npm install && npm run build
```

**Want to reinstall cleanly**

```bash
./scripts/install.sh   # safe to re-run, idempotent
```

</details>

<details>
<summary><strong>What Tracecode does not do</strong></summary>

- Does not modify your code
- Does not send data anywhere — everything stays in `~/.tracecode/`
- Does not require an account or API key
- Does not capture terminal output or conversation content — only filesystem events, git state, and shell commands
- Does not integrate with CI, GitHub, Slack, or any external service
- Does not support team or shared sessions — this is a personal tool

**Current limitations**

- macOS and Linux only — Windows not supported
- Git projects only — file persistence analysis requires git
- Single-machine — no sync across devices
- Test detection works automatically with pytest and JUnit XML; other frameworks require a configured test command

</details>

<details>
<summary><strong>Privacy</strong></summary>

All data is stored locally in `~/.tracecode/tracecode.db`. Nothing is transmitted to any server. The UI binds to `127.0.0.1` only.

Tracecode records:

- File paths modified during sessions (not file contents)
- Shell commands matching risky or catastrophic patterns (command string only, truncated to 500 characters)
- Git metadata: branch names, commit SHAs, diff line counts
- Session timing

</details>

<details>
<summary><strong>Developer notes</strong></summary>

**Requirements:** Python 3.11+, Node.js 18+, Claude Code

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

</details>
