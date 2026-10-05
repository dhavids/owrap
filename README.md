# owrap

## Session workflows

Sessions keep their context, plans, and activity under `OWRAP_HOME`. A project
or repository target identifies where durable work belongs; several sessions
can target the same project or subproject.

- `owrap spawn [name]` starts a child session with the current project's or
  repository's target and repository links. It creates no checkout.
- `owrap temp [name]` starts an independent session with no project target.
  Without a name, owrap assigns `temp-<session-id>`. Its context, plans, and
  logs live in `OWRAP_HOME/sessions/<session-id>/`, like other sessions.
- `owrap main` returns an active project session to its main record.
- `owrap sub <id> [-f]` selects or creates a regular subproject; close names
  require correction or `-f` before creation.
- `owrap subs` lists the active project's subprojects.
- `owrap branch [name] [--ref <git-ref>]` starts a child session and makes one
  Git worktree per linked repository in `<workspace>/branches/<session-id>/`.
  The source checkouts must be clean. This command does not merge code.
- `owrap branch merge [--session <id>] [--repo <id>]` previews code changes.
  Add `--apply` to merge; a branch with several repositories requires `--repo`
  for each merge.
- `owrap collapse [--session <id>]` previews new child context entries. Add
  `--apply` to copy them to the parent and return the window there. Branch
  sessions require their code to be merged first.
- `owrap branch cleanup --session <child-id>` previews worktree removal. Add
  `--apply` after code merge and session collapse. Plain child and temp
  sessions never create worktrees.

`attach` connects a window to an existing session. It does not change the
session's project target. Legacy research/area sessions retain their existing
`spawn` behavior during migration.
`owrap stat` shows each session's type: `normal`, `spawn`, `branch`, or `temp`.

Session-aware bridge between the planner (currently Claude Code) and opencode (executor). A planner instance designs plans and dispatches work; an opencode-backed executor does the actual reading, writing, and running. owrap provides background agents and task dispatch, parallel session isolation, and graceful server lifecycle management.

## Requirements

- Claude Code (VSCode or CLI)
- opencode CLI
- Python >= 3.10
- PyYAML for the Python interpreter used to run `setup.py`

## Install

```bash
git clone <repo_url>
cd owrap
python3 -m pip install PyYAML
python3 setup.py     # installs launchers for this checkout
```

The live checkout installs launchers to `~/bin`; `dev/owrap` installs them to
`dev/owrap/files/bin` with its own runtime home. After a code update, run
`python3 update.py` from that checkout to refresh all six launchers. Restart
running owrap processes to load changed Python code.

## Getting Started

For ordinary work, use the installed `~/bin/owrap`. Its session, memory, and
logs use the live OWRAP_HOME. Edit owrap code in the `dev/owrap` checkout and
run its tests there. Use `dev/owrap/files/bin/owrap` only for isolated
development simulations; do not attach normal work sessions to dev state.
Never promote dev code to the live checkout without an explicit user request.
The `dev/owrap` checkout uses the repository's `dev` branch. The live `owrap`
checkout uses `main`. Tests and pytest configuration stay on `dev`.
`deploy.py` exports a filtered committed `dev` snapshot into the live checkout,
excluding tests, development state, and deployment files. It previews by
default; `--apply` creates the live `main` promotion commit and refreshes the
installed launchers. Add `--push` to push `main` to the shared origin.

### Promotion

Promotion starts from a reviewed commit on `dev`. The development checkout
must be clean. Preview the filtered release before applying it:

```bash
cd /home/humble/marl/dev/owrap
python3 deploy.py
python3 deploy.py --apply
```

The first promotion creates `main` at the current live snapshot and leaves the
existing `live` branch at that snapshot as a rollback reference. Later
promotions add a commit to `main` with both the previous live commit and the
reviewed `dev` commit as parents. Run `--push` only when the promoted commit
should be published to `origin/main`.

### Legacy record migration

`owrap migrate` previews conversion of legacy project, memory, todo, and
session records. `--map` accepts a reviewed YAML file with explicit repository
checkouts and project links:

```yaml
repositories:
  example-repo:
    checkout: /absolute/path/to/example-repo
    remote: git@example.com:team/example.git
projects:
  example-project: [example-repo]
  project-without-code: []
```

An empty list explicitly records that a project has no repository. An omitted
project is reported as unmapped. Preview and apply use the same inputs:

```bash
owrap migrate --home /path/to/.owrap --docs-root /path/to/research \
  --map /path/to/migration.yaml
owrap migrate --home /path/to/.owrap --docs-root /path/to/research \
  --map /path/to/migration.yaml --apply
```

Before applying, archive both `OWRAP_HOME` and the documentation repository to
a location outside those trees. Stop active owrap jobs during the migration.
To roll back, keep the failed trees for inspection, extract both archives into
sibling staging directories on the same filesystems, verify them, then rename
the restored directories into their original paths. Restore the pair together;
the session identities and project records form one migration state.

```bash
~/bin/owrap start owrap             # current live CLI: begin an owrap session
```

The development CLI adds `owrap start --project <id>` for a project session.
`setup` writes a workspace config under `OWRAP_HOME/configs/` and stages
`CLAUDE.md`, `AGENTS.md`, and the `self.md` reference pages under
`OWRAP_HOME/staged/<workspace>/`. After starting or attaching a session, run
`owrap sync` to install workspace settings and hooks.
In the development checkout, `setup` accepts only workspace and memory paths
under `dev/owrap/files/`.

Harness templates live in `templates/claude/` and `templates/codex/`.
Both `setup` and `sync` stage each harness's files; `sync` installs the
Claude settings and Codex hooks into the workspace. The planner, executor,
`self.md` pages, and base config remain shared templates at the top level.
Planner and executor manuals go to `CLAUDE.md` and `AGENTS.md` by default.
Workspace-owned additions live in `docs_root/instruction.md`. Its `## Planner`,
`## Executor`, and `## Self` sections are added to the corresponding staged
documents. Generic `self.md` pages are never copied into `docs_root`.
Use `owrap setup <path> --planner claude --executor opencode` to select the
harness for each role. `claude` uses `CLAUDE.md`; `codex` and `opencode` use
`AGENTS.md`. Repeat `--planner` or `--executor` to use a role with multiple
harnesses. For example, `--planner claude --executor claude` puts both manuals
in `CLAUDE.md`. Each harness has its own `allow.json` for `owrap p`.

### Use `owrap p` in Codex

1. Run `owrap sync`.
2. Add this to `~/.codex/config.toml`, using your workspace's absolute path:

   ```toml
   [projects."/absolute/path/to/workspace"]
   trust_level = "trusted"
   ```

3. Start a new Codex session, open `/hooks`, and trust the `owrap p` hooks.

## OWRAP_HOME

In the live checkout, `OWRAP_HOME` resolves in this order: `$OWRAP_HOME` env
var, `~/.owrap_home` pointer file, then `~/.owrap`. In `dev/owrap`, it defaults
to `dev/owrap/files/state`; an explicit value must remain under
`dev/owrap/files`. The development launchers set this value themselves.

For relocation, use `owrap update-home <path>` to move only the pointer or `--migrate` to perform a full atomic relocation of the owrap runtime directory. See [Sessions § OWRAP_HOME](templates/self/sessions.md#owrap_home).

## Configuration

Base config: `templates/config.json` → copy to `OWRAP_HOME/configs/base.json`.

| Key | Type | Default | Description |
|---|---|---|---|
| `owrap_runner_enabled` | bool | `true` | Runner on/off switch. When `false`, dispatch tooling (`orun`/`oexec`/`oagent`/`owrap f`) is disabled and planner works directly. |
| `owrap_context_manager_enabled` | bool | `true` | Gates the context-manager pipeline (Update Context/Update Protocol dispatch, including PreCompact), independent of the runner switch above. |
| `permit_bypass_all` | bool | `false` | When `true`, `owrap p` auto-approves every Bash/Write/Edit call with no rule matching. Explicit opt-in only — never implied by the runner switch. |
| `runner_allow_all` | bool | `false` | Always pass `--dangerously-skip-permissions` to opencode dispatches. |
| `runner_use_oread` | bool | `true` | Require file reads through `oread` (enables Read in permission matcher). |
| `context_injection_enabled` | bool | `true` | Inject session context file into task/msg prompts. |
| `default_research` | string | — | Default target for legacy positional `start`. |
| `workspace` | string | — | Path to the project root. |
| `docs_root` | string | — | Root for projects, repositories, and the user-owned `instruction.md`. |
| `research_root` | string | — | Legacy alias read during migration. |
| `use_multiple_servers` | bool | `false` | Enable server pool mode. |
| `max_servers` | int | `1` | Maximum concurrent opencode servers. |
| `min_servers` | int | `1` | Minimum live servers the daemon maintains. |
| `max_requests_per_server` | int | `10` | Request quota per server before graceful eviction. |
| `idle_shutdown_s` | float | `300` | Idle seconds before server shutdown. |
| `daemon_interval_s` | float | `10` | Seconds between daemon pool-lifecycle checks. |
| `ctx_check_interval_s` | float | `300` | Seconds between the daemon's background checks for an attached window's unprocessed transcript diff — dispatches an Update Context/Update Protocol pass automatically when one exists. |
| `runner_model` | string | — | Model for regular runner dispatch (`orun`/`oexec`). |
| `context_manager_model` | string | — | Model for context-manager tasks (Update Context/Update Protocol dispatch). |
| `context_fallback_model` | string | — | Fallback model when `context_manager_model` isn't set. |
| `daemon_default_model` | string | — | Reserved for the daemon; not currently consumed (the daemon is pure lifecycle management, no model calls). |
| `msg_kill_s` / `task_kill_s` / `exec_kill_s` | int | `30`/`60`/`120` | No output kill timeouts for msg, task, exec jobs. |
| `stall_notify_s` | int | `120` | Seconds before notification for a stalled job. |
| `watchdog_poll_s` | int | `10` | Watchdog polling interval. |
| `expected_duration_*` | int | varies | Expected duration thresholds for msg/read/task/exec. |

## Core Commands

### Task dispatch (`orun`)

Dispatches inline messages, file tasks, and parallel jobs to the executor. Most common: `orun --msg "..."` (foreground) or `orun` (file task from `input.md`, auto-background). See [Commands § Dispatch commands](templates/self/commands.md#dispatch-commands).

### Plan execution (`oexec`)

Executes the active `[ACTIVE]` plan block. Most common: `oexec` (auto-background). See [Commands § Dispatch commands](templates/self/commands.md#dispatch-commands).

### Sub-agent dispatch (`oagent`)

Dispatches sub-agent payloads via heredoc with configurable timeout and model override. Most common: `oagent <<'OAGENT_PAYLOAD_END' ... OAGENT_PAYLOAD_END`. See [Commands § Dispatch commands](templates/self/commands.md#dispatch-commands).

### Fallback dispatch (`owrap f`)

Runs `--execf` or `--taskf` directly without the server pool; mode inferred from filename. See [Recovery § Fallback dispatch](templates/self/recovery.md#fallback-dispatch).

### File reading (`oread`)

Reads files, directories, grep patterns, summaries, and targeted queries through the executor. Most common: `oread -f <file>`. See [Commands § Dispatch commands](templates/self/commands.md#dispatch-commands).

### Notebook reading (`nbread`)

Lists and displays Jupyter notebook cells. Most common: `nbread <nb.ipynb>` (list cells) or `nbread <nb.ipynb> <N>` (show cell N). Use `nbread -h` for options.

### Session lifecycle

Manages sessions, servers, and templates. Key commands: `owrap start --project <id>` (begin a project session), `owrap refresh`, `owrap end`, `owrap sync`, `owrap stat`, and `owrap get <what>`. See [Sessions](templates/self/sessions.md) and [Commands](templates/self/commands.md).

### Wait (`owait`)

Blocks until dispatched jobs complete. Most common: `owait input` (between parallel dispatches) or `owait run` (next task completion). See [Commands § Dispatch commands](templates/self/commands.md#dispatch-commands).

## Server Management

- **Graceful draining**: Unresponsive servers or those hitting their request quota are marked *draining*. In this state, no new work is routed to them, but in-flight requests are allowed to finish. The servers are then reaped once idle, not killed outright.
- **Daemon**: Manages the server pool — shuts down idle servers, maintains `min_servers`. Spawned automatically on first pooled dispatch and stays running from then on (does not self-exit on idle).
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

Expected-duration thresholds used by the watchdog to judge stalls (e.g. `expected_duration_msg`, `expected_duration_task`, kill timeouts). See [Commands § Duration defaults](templates/self/commands.md#duration-defaults).

## Exit codes

See [Commands § Exit codes](templates/self/commands.md#exit-codes) for redispatch guidance.

## Parallel Task Dispatch

Write a task to the session `input.md`, dispatch with `orun`, then `owait input` before writing the next — up to 5 tasks can run simultaneously. Collect results with `owait run` per completion. See [Commands § Dispatch commands](templates/self/commands.md#dispatch-commands).

## Troubleshooting

**No server available / NO_SERVER error**: Run `owrap stat` to check pool status. Servers hitting `max_requests_per_server` are gracefully drained and replaced. Use `owrap f <path>` as a fallback that bypasses the pool entirely.

**Task/exec times out**: Default ceilings are 600s. Extend with `-t <secs>`. If the job is stuck, `owrap abort <target>` sends SIGTERM.

**Stalled job notification**: After `stall_notify_s` (default 120s) with no output, a watchdog notification fires. If the server is unresponsive, it is marked draining and will be reaped when idle.

**Template changes not picked up**: Run `owrap sync`, then dispatch the sync task it prints via `orun`.

**owrap_runner_enabled = false**: Dispatch tooling is disabled; planner works directly. Note this does not by itself grant unrestricted command access — that requires the separate, explicit `permit_bypass_all` flag.

## Tests

```bash
cd /home/humble/marl/dev/owrap
/home/humble/e-swarm/bin/python3 -m pytest tests/ -v
```

The suite refuses to run outside the `dev/owrap` checkout. It creates a private
`OWRAP_HOME` under `dev/owrap/files/test-runs`, redirects per-test files to
pytest temporary directories, and uses ports starting at 15096. It does not
run global server cleanup. See [tests/md/run_tests.md](tests/md/run_tests.md)
for the coverage table and manual smoke tests.
