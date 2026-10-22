# owrap

**Harness-independent memory and cheap execution for AI coding agents.**

owrap is a CLI that gives a frontier-model planner (Claude Code or Codex)
three things:

- **Segmented memory that outlives the harness.** Project records, repository
  changes, and per-session context live as plain files in your workspace,
  organized by project, subproject, and repository rather than by chat.
  Because they belong to the workspace and not to any one agent, a different
  harness or session can pick up the project files and continue seamlessly.
- **Automatic compaction through opencode.** owrap keeps the records and each
  session's `context.md` current from the transcript (`owrap
  ctx`/`updr`/`uall`, a PreCompact hook, and a background daemon check),
  dispatching the work to opencode **free models** instead of the planner's
  own tokens. After a compaction the planner re-reads its state instead of
  starting cold. Setting a project's `risk` level to `high` disables this.
- **Execution offloaded to opencode.** The frontier model plans and reviews;
  reads, edits, and long tasks go to an opencode-backed executor (`owrap
  read`/`exec`/`agent`/`task`, or `owrap f`), with session isolation, a
  server pool, and watchdog-based stall/failure handling.

Memory management and execution are independent. Memory and compaction run
regardless of whether execution is enabled, except for *high-risk projects*.
Execution can be turned off with `owrap_runner_enabled: false`, and the
planner then works directly. If opencode is unreachable (`owrap get
opencode`), the planner can also manage memory itself via `owrap ctx get
template`/`ctx done`.

Full reference docs — session lifecycle, every command, config keys,
timeouts, troubleshooting — live under `templates/self/*.md` and are staged
into each workspace's `CLAUDE.md`/`AGENTS.md`/`self.md` by `owrap sync`. This
file covers only install and setup.

## Requirements

- Claude Code (VSCode or CLI) and/or Codex CLI, as the planner
- opencode CLI, for compaction and execution
- Python >= 3.10
- PyYAML for the Python interpreter used to run `setup.py`

## Install

```bash
git clone https://github.com/dhavids/owrap.git
cd owrap
python3 -m pip install PyYAML
python3 setup.py     # installs the owrap launcher for this checkout
```

This installs the `owrap` launcher to `~/bin`. After a code update, run
`python3 update.py` to refresh it, and restart any running owrap processes
to load the changed code.

For a new workspace, run `owrap setup <workspace_path> --planner claude
--executor opencode` first — it writes the workspace config and stages
`CLAUDE.md`/`AGENTS.md`/`self.md` (`claude` → `CLAUDE.md`; `codex`/`opencode`
→ `AGENTS.md`). Workspace-owned additions live in `docs_root/instruction.md`;
its `## Planner`/`## Executor`/`## Self` sections are merged into the
corresponding staged document on every sync.

Then start a session and sync workspace settings/hooks:

```bash
~/bin/owrap start project <project_name>
owrap sync
```

### Permissions (`owrap p`)

`owrap p` is owrap's own permission check — any harness can wire it up to
gate tool calls. It reads the tool call from stdin, loads the workspace's
staged allow rules, and approves or denies by pattern match.
`permit_bypass_all` auto-approves everything; otherwise anything not
matching an allow rule is denied. Claude and Codex are the two harnesses
currently wired up:

- **Claude**: staged into `CLAUDE.md`'s `settings.json` as a single
  `PreToolUse` hook running `owrap p`, with `defaultMode: dontAsk` so Claude
  never falls back to its own interactive prompt — owrap's hook is the only
  gate.
- **Codex**: staged into `AGENTS.md`'s `hooks.json` as two hooks on `^Bash$`
  — `PreToolUse` and `PermissionRequest` — both running `owrap p`, since
  Codex's permission-request flow needs its own matching hook. One-time
  setup:
  1. Run `owrap sync`.
  2. Add to `~/.codex/config.toml` (absolute workspace path):
     ```toml
     [projects."/absolute/path/to/workspace"]
     trust_level = "trusted"
     ```
  3. Start a new Codex session, open `/hooks`, and trust the `owrap p` hooks.

## Reference

- Session lifecycle, `OWRAP_HOME`, spawn/branch/collapse: `templates/self/sessions.md`
- Commands, server management, timeouts, troubleshooting: `templates/self/commands.md`
- Context/record update behavior: `templates/self/context.md`
- Recovery, decision pruning, fallback dispatch: `templates/self/recovery.md`
- Config keys: `templates/self/commands.md` § Configuration
