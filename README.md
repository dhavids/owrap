# owrap

Session-aware bridge between Claude Code (planner) and opencode (executor). Background task dispatch, parallel session isolation, and Python mtime-polling completion notifications.

## Requirements

- Claude Code (VSCode or CLI)
- opencode CLI
- Python >= 3.10

## Installation

```bash
git clone <repo_url>
cd owrap
pip install -e .
python3 setup.py     # installs shims to ~/bin/, checks deps
```

Make sure `~/bin/` is on your `$PATH`.

## Updating Shims

After `git pull`, re-install shims only (Python source is live via editable install):

```bash
python3 update.py
```

## Getting Started

```bash
~/bin/owrap setup [path] [--name <project>] [--workspace <ws>] [--research-root <path>]
~/bin/owrap start <research_name>
```

`setup` writes `~/.owrap/configs/base.json`, installs templates, and prints the FILES/SETTINGS instructions Claude needs to read. `start` generates a session ID, starts the server, and prints the orientation block.

## Updating Planner Files

When templates change, re-stage and apply:

```bash
~/bin/owrap sync
# then tell Claude: dispatch the sync task via orun
```

Merge rule: sections in the template but missing from the installed file are added; existing content is never overwritten.

## Running Tests

```bash
cd owrap && python3 -m pytest tests/ -v
```

All output is isolated to `tmp_path` per test. Servers are killed before and after the full suite. See `tests/md/run_tests.md` for the coverage table and manual smoke tests.

## Limits and Timeouts

| Limit | Value | Notes |
|---|---|---|
| `orun --msg` max length | 1024 chars | Longer tasks should use file-based `orun` via `input_<id>.md` |
| `oread -d` / `-s` timeout | 55–180s (scales with file size) | Partial output on expiry; use `-t <secs>` to extend |
| `oread` auto-summarise threshold | 8000 chars | Files above this are forwarded to opencode for summary |

## Configuration

Base config: `~/.owrap/configs/base.json`. Copy `templates/config.json` there to start.

| Key | Type | Description |
|---|---|---|
| `default_research` | string | Default project name when no research is specified |
| `project_root` | string | Path to the project root (`CLAUDE.md`, `AGENTS.md`, `.claude/`) |
| `research_root` | string | Path to the research folder (`self.md`; often `<project_root>/docs/research`) |
| `allow_all` | bool | Always pass `--dangerously-skip-permissions` to opencode |
| `oread_always` | bool | Require all file reads to go through `oread` (default: `true`) |
| `max_servers` | int | Maximum concurrent opencode servers. Pool is active when `max_servers >= min_servers` (default: `1`) |
| `min_servers` | int | Minimum live servers the keepalive maintains (default: `2`) |
| `idle_shutdown_s` | float | Idle seconds before server shutdown (default: `600`) |
| `keepalive_interval_s` | float | Seconds between keepalive ping cycles (default: `10`) |
| `keepalive_idle_exit_s` | float | Seconds with empty pool before keepalive exits (default: `300`) |

## Prompt Styles

`oread -s` / `oread -d` auto-detect style from file extension. Override with `-p <style>`. Run `~/bin/oread --list-styles` to see all extension defaults.

| Style | Output |
|---|---|
| `terse` | Max 5 bullets. Default for `.md`, `.txt`, `.rst`. |
| `code` | Purpose, key classes/functions, side-effects. 20 lines max. Default for `.py`, `.sh`, `.js`, `.ts`, etc. |
| `structured` | `## Purpose` / `## Key Parts` / `## Watch-outs`. 25 lines max. Default for `.yaml`, `.json`, `.toml`, etc. |
| `bullets` | What, why, how, gotchas. 10 bullets max. Default for `.csv`, `.log`. |
| `exec` | Single prose paragraph, 4–6 sentences. |
| `default` | Direct answer, configurable line limit. |
| `deep` | Strategic read: flags None/stub values, disabled features, numeric inconsistencies. 30 lines max. |

## Commands Reference

| Command | What it does |
|---|---|
| `~/bin/owrap start [name]` | Start session: generate ID, start server, print orientation |
| `~/bin/owrap refresh [name]` | Re-validate session; re-print orientation |
| `~/bin/owrap restart [name]` | End current session + start fresh; `--force` kills server first |
| `~/bin/owrap stop` | End current session (server kept if others active); `--force` kills server + clears all |
| `~/bin/owrap end [target]` | End this session only (server keeps running) |
| `~/bin/owrap attach <session_id>` | Bind this Claude window to an existing session |
| `~/bin/owrap stat [filter]` | Show sessions, server pool (alive/dead, warm/cold, load), keepalive status |
| `~/bin/owrap cleanup [id]` | Remove stale sessions; optional partial ID to target one |
| `~/bin/owrap finish <target>` | Kill a running job by target (`exec`, `task1`, `msg1`, …) — SIGTERM to its PID |
| `~/bin/owrap sync` | Re-stage templates and write sync task for planner to apply |
| `~/bin/owrap trim` | Kill pool servers with no active sessions |
| `~/bin/owrap killservers [--session <id>]` | Kill all servers and running tasks without touching session/context state |
| `~/bin/owrap keepalive` | Run the keepalive daemon (pings servers, shuts down idle ones) |
| `~/bin/owrap setup [path] [--name] [--workspace] [--research-root]` | Configure base.json, install templates |
| `~/bin/oread -f <file>` | Print file; if >8000 chars, summarise via opencode |
| `~/bin/oread -f <file> -v` | Full cat, no summarise threshold |
| `~/bin/oread -f <dir>` | List directory (instant) |
| `~/bin/oread -g <pattern> [-f <path>]` | Grep recursively (instant) |
| `~/bin/oread -f <file> -s [-p <style>]` | Summarise via opencode |
| `~/bin/oread -f <file> -d "..."` | Targeted query; timeout scales 55–180s with file size |
| `~/bin/oread -f <file> -d "..." -t <secs>` | Targeted query with custom timeout |
| `~/bin/oread -i <id> -f <file>` | Tag read output with `[r:<id>]` for parallel tracking |
| `~/bin/oread --list-styles` | List all styles and extension defaults |
| `~/bin/orun --msg "..."` | Inline task, ≤1024 chars (foreground); `--msg -` reads from stdin |
| `~/bin/orun -i <id> --msg "..."` | Parallel tagged msg: output prefixed `[m:<id>]` |
| `~/bin/orun --msg "..." -t <secs>` | Custom timeout (default: 180s) |
| `~/bin/orun [--input <path>]` | File task from `input_<id>.md` or custom path (auto-background) |
| `~/bin/oexec` | Execute active plan (auto-background) |
| `~/bin/owait run <id>` | Block until run task completes |
| `~/bin/owait exec <id>` | Block until exec completes |
| `~/bin/owait read <id>` | Block until read completes |
| `~/bin/owait msg <id>` | Block until tagged `--msg` completes |
| `~/bin/owait input` | Block until `input_<id>.md` is cleared |

## Parallel Task Dispatch

```
write task A → input_<id>.md
~/bin/orun          ← picks up, creates task1.md, clears input, backgrounds
~/bin/owait input   ← blocks until cleared
write task B → input_<id>.md
~/bin/orun          ← creates task2.md, backgrounds
~/bin/owait input
# task1 and task2 running in parallel
~/bin/owait run <id>   ← unblocks on first completion
~/bin/owait run <id>   ← unblocks on second
```

Use `--fg` on `orun`/`oexec` to force foreground. Cancel a job with `owrap finish <target>` — reads the PID from `~/.owrap/running/` and sends SIGTERM.
