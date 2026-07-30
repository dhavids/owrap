# owrap

Session-aware bridge between the planner (currently Claude Code) and opencode (executor). A planner instance designs plans and dispatches work; an opencode-backed executor does the actual reading, writing, and running. owrap provides background task dispatch, parallel session isolation, and graceful server lifecycle management.

## Requirements

- Claude Code (VSCode or CLI)
- opencode CLI
- Python >= 3.10

## Install

```bash
git clone <repo_url>
cd owrap
pip install -e .
python3 setup.py     # installs shims to ~/bin/
```

Ensure `~/bin/` is on your `$PATH`. After `git pull`, re-run `python3 setup.py` to refresh shims.

## Getting Started

```bash
owrap setup <path>                  # configure workspace, install templates
owrap start <research> [area] [child]  # generate session ID, start server, print orientation
```

`setup` writes a workspace config under `OWRAP_HOME/configs/`, installs templates, and prints the FILES/SETTINGS block the planner needs. `start` generates a session ID, resolves or starts a server, and prints the orientation block. `area` scopes work within a research project; `child` creates/binds a child area (`<area>-<child>`).

## OWRAP_HOME

`OWRAP_HOME` resolves in this order: `$OWRAP_HOME` env var (if set) > contents of `~/.owrap_home` pointer file (if it exists) > default `~/.owrap`. Both the Python package and every bash shim (`owrap`, `orun`, `oexec`, `owait`, `oread`) resolve it the same way. For relocation, use `owrap update-home <path>` (pointer-only) or `--migrate` (full atomic move with backup) — see `self.md` § OWRAP_HOME for the full behavior.

## Configuration

Base config: `templates/config.json` → copy to `OWRAP_HOME/configs/base.json`.

| Key | Type | Default | Description |
|---|---|---|---|
| `owrap_enabled` | bool | `true` | Master on/off switch. When `false`, dispatch tooling is disabled and all commands pass through directly. |
| `allow_all` | bool | `false` | Always pass `--dangerously-skip-permissions` to opencode. |
| `oread` | bool | `true` | Require file reads through `oread` (enables Read in permission matcher). |
| `context_enabled` | bool | `true` | Inject session context file into task/msg prompts. |
| `default_research` | string | — | Default project name when no research is specified. |
| `workspace` | string | — | Path to the project root. |
| `research_root` | string | — | Path to the research folder (`self.md`). |
| `use_multiple_servers` | bool | `false` | Enable server pool mode. |
| `max_servers` | int | `1` | Maximum concurrent opencode servers. |
| `min_servers` | int | `1` | Minimum live servers the keepalive maintains. |
| `max_requests_per_server` | int | `10` | Request quota per server before graceful eviction. |
| `idle_shutdown_s` | float | `240` | Idle seconds before server shutdown. |
| `keepalive_interval_s` | float | `10` | Seconds between keepalive ping cycles. |
| `keepalive_idle_exit_s` | float | `1800` | Seconds with empty pool before keepalive exits. |
| `keepalive_ping_model` | string | — | Model used for keepalive pings. |
| `exec_model` | string | — | Default model for exec dispatches. |
| `msg_kill_s` / `task_kill_s` / `exec_kill_s` | int | `30`/`60`/`120` | Kill timeouts for msg, task, exec jobs. |
| `stall_notify_s` | int | `120` | Seconds before stalling job notification. |
| `watchdog_poll_s` | int | `10` | Watchdog polling interval. |
| `expected_duration_*` | int | varies | Expected duration thresholds for msg/read/task/exec. |

## Core Commands

### Task dispatch (`orun`)

Dispatches inline messages, file tasks, and parallel jobs to the executor. Most common: `orun --msg "..."` (foreground) or `orun` (file task from `input.md`, auto-background). See `self.md` § orun for the full flag reference.

### Plan execution (`oexec`)

Executes the active `[ACTIVE]` plan block. Most common: `oexec` (auto-background). See `self.md` § oexec for the full flag reference.

### Sub-agent dispatch (`oagent`)

Dispatches sub-agent payloads via heredoc with configurable timeout and model override. Most common: `oagent <<'OAGENT_PAYLOAD_END' ... OAGENT_PAYLOAD_END`. See `self.md` § oagent for the full flag reference.

### Fallback dispatch (`owrap f`)

Runs `--execf` or `--taskf` directly without the server pool; mode inferred from filename. See `self.md` § Fallbacks for the full behavior including stall detection and status fields.

### File reading (`oread`)

Reads files, directories, grep patterns, summaries, and targeted queries through the executor. Most common: `oread -f <file>`. See `self.md` § oread for the full flag reference.

### Notebook reading (`nbread`)

Lists and displays Jupyter notebook cells. Most common: `nbread <nb.ipynb>` (list cells) or `nbread <nb.ipynb> <N>` (show cell N). See `self.md` § nbread for the full flag reference.

### Session lifecycle

Manages sessions, servers, templates, and research areas. Key commands: `owrap start <research>` (begin session), `owrap refresh` (re-validate), `owrap stop` / `owrap end` (end session), `owrap sync` (re-stage templates), `owrap stat` (inspect state), `owrap get <what>` (read session files). See `self.md` § owrap for the full flag reference.

### Wait (`owait`)

Blocks until dispatched jobs complete. Most common: `owait input` (between parallel dispatches) or `owait run` (next task completion). See `self.md` § owait for the full flag reference.

## Server Management

- **Graceful draining**: Unresponsive servers or those hitting their request quota are marked *draining* — no new work is routed to them, but in-flight requests complete. They are reaped once idle, not killed outright.
- **Keepalive**: Pings servers periodically, shuts down idle ones. Runs automatically when pool is active.
- `owrap trim` — Kill pool servers with no active sessions.
- `owrap killservers [--session <id>]` — Kill all servers and running tasks.

## Timeouts

| Dispatch | Default hard ceiling | Override |
|---|---|---|
| `orun --msg` | 180s | `-t <secs>` |
| `orun` (file task) | 600s | `-t <secs>` |
| `oexec` | 600s | `-t <secs>` |
| `oagent` | 120s | `-t <secs>` |

The 600s hard wall-clock timeout on task/exec dispatches can be overridden per-invocation via `-t`/`--timeout`.

## Duration defaults

Expected-duration thresholds used by the watchdog to judge stalls (e.g. `expected_duration_msg`, `expected_duration_task`, kill timeouts). See `self.md` § Duration defaults for the full table.

## Exit codes

See `self.md` § Exit codes for the full table and redispatch guidance.

## Parallel Task Dispatch

Write a task to the session `input.md`, dispatch with `orun`, then `owait input` before writing the next — up to 5 tasks can run simultaneously. Collect results with `owait run` per completion. See `self.md` § orun for the full dispatch pattern and flag reference.

## Troubleshooting

**No server available / NO_SERVER error**: Run `owrap stat` to check pool status. Servers hitting `max_requests_per_server` are gracefully drained and replaced. Use `owrap f <path>` as a fallback that bypasses the pool entirely.

**Task/exec times out**: Default ceilings are 600s. Extend with `-t <secs>`. If the job is stuck, `owrap finish <target>` sends SIGTERM.

**Stalled job notification**: After `stall_notify_s` (default 120s) with no output, a watchdog notification fires. If the server is unresponsive, it is marked draining and will be reaped when idle.

**Template changes not picked up**: Run `owrap sync`, then dispatch the sync task it prints via `orun`.

**owrap_enabled = false**: All dispatch tooling is disabled; commands pass through directly to opencode. Useful for debugging or when you want raw opencode behavior.

## Tests

```bash
cd owrap && python3 -m pytest tests/ -v
```

All output is isolated to `tmp_path` per test. Servers are killed before and after the full suite. See `tests/md/run_tests.md` for the coverage table and manual smoke tests.
