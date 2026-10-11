# Commands

Use `owrap <command> -h` for exact options. Commands below describe the
current session model; existing research and area forms remain available
only during migration.

Full argument/flag syntax for every command below lives in Full Command
Reference at the end of this file — the tables below are for workflow
grouping and the one-line purpose, not the exact shape.

Graceful draining (Server management, below): an unresponsive server, or
one past `max_requests_per_server`, stops receiving new work but finishes
in-flight requests before being reaped. The daemon manages the pool —
spawns on first pooled dispatch, maintains `min_servers`, shuts down idle
servers past `idle_shutdown_s`.

<!-- BEGIN GENERATED: workflow tables (templates/build.py) -->
## Session commands

| Command | Effect |
|---|---|
| `owrap project start` | Start a targeted project session |
| `owrap project add` | Select or create a regular subproject |
| `owrap project set` | Return the current project session to main, or select an existing subproject |
| `owrap session add` | Create a child session with inherited target, or an independent one via `temp` |
| `owrap session done` | Preview or merge child context |
| `owrap session attach` | Bind this window to a session |
| `owrap session refresh` | Refresh session context and orientation |
| `owrap session stop` | Stop the current session (reversible via `owrap session restore`) |
| `owrap stat do` | Show sessions, types, recent tasks, live stages, and server status |
| `owrap worktree add` | Create a child session with Git worktrees |
| `owrap worktree done` | Preview or merge branch code |
| `owrap worktree clear` | Remove merged branch worktrees |


## Record and context commands

| Command | Effect |
|---|---|
| `owrap ctx start` | Queue a session context update |
| `owrap decision get` | List decisions for a project/repository/session target |
| `owrap project get` | Read project/subproject goals and decisions, or report identity |
| `owrap sync do` | Stage and merge workspace instructions |
| `owrap todo get` | List goals for a project/repository/session target |
| `owrap updr start` | Queue durable record updates, optionally with context |


## Dispatch commands

| Command | Effect |
|---|---|
| `owrap exec start` | Execute the active session plan |
| `owrap fallback start` | Run a direct fallback task or plan |
| `owrap read start` | Read a file or list a directory |
| `owrap session wait` | Wait for queued input to clear |
| `owrap task start` | Run one inline task, or dispatch a task file |


## Server management

| Command | Effect |
|---|---|
| `owrap daemon start / stop / restart` | Manage the background daemon process directly |
| `owrap daemon get` | Report whether the daemon is running (and its pid) |
| `owrap daemon kill` | Kill all running tasks, pool servers, and the daemon itself (optionally scoped to one session) |
| `owrap daemon clean` | Remove stale session/context/server-log files |
<!-- END GENERATED: workflow tables -->


## Troubleshooting

| Symptom | Action |
|---|---|
| `NO_SERVER` / no server available | `owrap stat` for pool status; `owrap fallback start <path>` bypasses the pool |
| Task/exec times out | Default ceiling 600s; extend with `-t <secs>`; `owrap task done <target>` sends SIGTERM |
| Stalled-job notification | Fires after `stall_notify_s` (default 120s) with no output; an unresponsive server is marked draining |
| Template changes not picked up | Run `owrap sync`, then dispatch the sync task it prints |
| `owrap_runner_enabled: false` | Dispatch tooling disabled, planner works directly — this alone does not grant unrestricted command access (`permit_bypass_all` is separate) |


## Configuration

Base config: `templates/config.json` → copy to `OWRAP_HOME/configs/base.json`.
Check `owrap self get config` for live values.

| Key | Type | Default | Description |
|---|---|---|---|
| `owrap_runner_enabled` | bool | `true` | Runner on/off switch. When `false`, dispatch tooling (`owrap read`/`exec`/`agent`/`task`, or `owrap fallback start`) is disabled and planner works directly. |
| `owrap_context_manager_enabled` | bool | `true` | Gates the context-manager pipeline (Update Context/Update Protocol dispatch, including PreCompact), independent of the runner switch above. |
| `permit_bypass_all` | bool | `false` | When `true`, `owrap p` auto-approves every Bash/Write/Edit call with no rule matching. Explicit opt-in only — never implied by the runner switch. |
| `runner_allow_all` | bool | `false` | Always pass `--dangerously-skip-permissions` to opencode dispatches. |
| `runner_use_oread` | bool | `true` | Require file reads through `owrap read` (enables Read in permission matcher). |
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
| `ctx_check_interval_s` | float | `600` | Seconds between the daemon's background checks for an attached window's unprocessed transcript diff -- an auto-dispatch still only fires once the excerpt clears `AUTO_CTX_MIN_CHARS` and this window's own 5-min cooldown, and backs off further (30m/1h/2h/5h) after repeated opencode-down failures. |
| `runner_model` | string | — | Model for regular runner dispatch (`owrap task start`/`owrap exec start`). |
| `context_manager_model` | string | — | Model for context-manager tasks (Update Context/Update Protocol dispatch). |
| `context_fallback_model` | string | — | Fallback model when `context_manager_model` isn't set. |
| `daemon_default_model` | string | — | Reserved for the daemon; not currently consumed (the daemon is pure lifecycle management, no model calls). |
| `msg_kill_s` / `task_kill_s` / `exec_kill_s` | int | `30`/`60`/`120` | No output kill timeouts for msg, task, exec jobs. |
| `stall_notify_s` | int | `120` | Seconds before notification for a stalled job. |
| `watchdog_poll_s` | int | `10` | Watchdog polling interval. |
| `expected_duration_*` | int | varies | Expected duration thresholds for msg/read/task/exec. |


## Duration defaults

Expected durations and watchdog limits come from workspace configuration.
Check `owrap self get config` for current values before changing timeouts.


## Exit codes

`0` means success. Other codes identify infra failure, timeout, crash,
unresponsiveness, or a watchdog termination. Read the dispatch output and
`owrap stat` before redispatching a failed task; rewrite a consumed input file
when its content needs correction.


<!-- BEGIN GENERATED: full command reference (templates/build.py) -->
## Full Command Reference

### `owrap agent`

| Action | Usage | Example |
|---|---|---|
| `start` | `<data> [--id <id>] [--timeout <s>] [--clear]` | `owrap agent start 'review owrap/cli.py for dead code'` |
| `get` | `<task_id>` | `owrap agent get a_1234` |
| `clear` | `` | `owrap agent clear` |


### `owrap backup`

| Action | Usage | Example |
|---|---|---|
| `add` | `[<target>]` | `owrap backup add` |
| `get` | `[<target>] [<timestamp>]` | `owrap backup get` |
| `restore` | `[<target>] <timestamp>` | `owrap backup restore myproject latest` |
| `remove` | `[<target>] [<which>]` | `owrap backup remove myproject` |


### `owrap branch`

| Action | Usage | Example |
|---|---|---|
| `add` | `<project_id> <branch_id> <parent_id> <repository_id> <branch_ref>` | `owrap branch add myproject feature-x main myrepo feature/x` |
| `done` | `<project_id> <branch_id> [apply]` | `owrap branch done myproject feature-x` |


### `owrap ctx`

| Action | Usage | Example |
|---|---|---|
| `start` | `` | `owrap ctx start` |
| `template` | `[subproject]` | `owrap ctx template` |
| `done` | `[--error <reason>]` | `owrap ctx done` |
| `add` | `<path> [path...] [--note <text>]` | `owrap ctx add owrap` |
| `wait` | `<job_id> [<timeout>]` | `owrap ctx wait 7f67b3760d` |


### `owrap daemon`

| Action | Usage | Example |
|---|---|---|
| `start` | `` | `owrap daemon start` |
| `stop` | `` | `owrap daemon stop` |
| `restart` | `` | `owrap daemon restart` |
| `get` | `` | `owrap daemon get` |
| `kill` | `[<session_id>]` | `owrap daemon kill` |
| `clean` | `[<session_id>]` | `owrap daemon clean` |


### `owrap decision`

| Action | Usage | Example |
|---|---|---|
| `add` | `<target> "<text>"` | `owrap decision add myproject "Keep the dev/live split"` |
| `remove` | `<target> <position>` | `owrap decision remove myproject 2` |
| `clear` | `[<target>]` | `owrap decision clear myproject` |
| `get` | `[<target> [<position|all>]]` | `owrap decision get myproject 1` |


### `owrap exec`

| Action | Usage | Example |
|---|---|---|
| `start` | `[--timeout <s>] [--no-watchdog]` | `owrap exec start` |
| `get` | `<task_id>` | `owrap exec get abc123` |


### `owrap fallback`

| Action | Usage | Example |
|---|---|---|
| `start` | `<path>` | `owrap fallback start plan.md` |
| `done` | `<task|exec>` | `owrap fallback done task` |
| `get` | `<task|exec>` | `owrap fallback get task` |


### `owrap model`

| Action | Usage | Example |
|---|---|---|
| `set` | `<slot> <query> [workspace]` | `owrap model set runner haiku` |


### `owrap permit`

| Action | Usage | Example |
|---|---|---|
| `set` | `<on|off> | <name> <on|off>` | `owrap permit set on` |
| `get` | `[<workspace>]` | `owrap permit get` |


### `owrap project`

| Action | Usage | Example |
|---|---|---|
| `start` | `[<id>]` | `owrap project start myproject` |
| `update` | `<old-id> <new-id>` | `owrap project update myproject renamed-project` |
| `add` | `<name> [force]` | `owrap project add docs` |
| `set` | `[<name>]` | `owrap project set` |
| `get` | `[main|subs|sub <name>|name|path]` | `owrap project get` |


### `owrap read`

| Action | Usage | Example |
|---|---|---|
| `start` | `<file> [--summarise] [--details <text>] [--grep <pattern>] [--id <id>]` | `owrap read start owrap/cli.py` |
| `get` | `<task_id>` | `owrap read get r_1234` |


### `owrap repository`

| Action | Usage | Example |
|---|---|---|
| `add` | `<repo_id> [checkout]` | `owrap repository add myrepo` |
| `update` | `<old_id> <new_id>` | `owrap repository update myrepo renamed-repo` |
| `remove` | `<repo_id>` | `owrap repository remove myrepo` |
| `attach` | `<repo_id> <project_id>` | `owrap repository attach myrepo myproject` |
| `detach` | `<repo_id> <project_id>` | `owrap repository detach myrepo myproject` |


### `owrap self`

| Action | Usage | Example |
|---|---|---|
| `get` | `[home|opencode [reason]|config|plan|input|output <kind>|runtime [history]|history] [--count <n>] [--tail <n>] [-g <pattern>] [--sid <id>]` | `owrap self get` |


### `owrap session`

| Action | Usage | Example |
|---|---|---|
| `add` | `[temp] [<label>]` | `owrap session add` |
| `done` | `[<sid>] [apply]` | `owrap session done` |
| `restore` | `<sid>` | `owrap session restore abc123` |
| `wait` | `[<timeout>]` | `owrap session wait` |
| `attach` | `<target>` | `owrap session attach abc123` |
| `refresh` | `` | `owrap session refresh` |
| `stop` | `[force]` | `owrap session stop` |


### `owrap setup`

| Action | Usage | Example |
|---|---|---|
| `do` | `<path> | --name <n> --workspace <path> [options]` | `owrap setup do /path/to/workspace` |


### `owrap stat`

| Action | Usage | Example |
|---|---|---|
| `do` | `` | `owrap stat do` |
| `get` | `<session_id>` | `owrap stat get abc123` |


### `owrap subproject`

| Action | Usage | Example |
|---|---|---|
| `update` | `<project_id> <old_id> <new_id>` | `owrap subproject update myproject docs renamed-docs` |
| `remove` | `<project_id> <sub_id>` | `owrap subproject remove myproject docs` |


### `owrap sync`

| Action | Usage | Example |
|---|---|---|
| `do` | `` | `owrap sync do` |


### `owrap task`

| Action | Usage | Example |
|---|---|---|
| `start` | `[--msg <text>] [--id <id>] [--input <path>]` | `owrap task start --msg 'summarise owrap/cli.py'` |
| `done` | `<target> [<session_id>]` | `owrap task done exec` |
| `get` | `<task_id>` | `owrap task get r_1234` |


### `owrap todo`

| Action | Usage | Example |
|---|---|---|
| `add` | `<target> [<position>] "<text>"` | `owrap todo add myproject "Fix the auth redirect bug"` |
| `update` | `<target> <position> "<text>"` | `owrap todo update myproject 2 "Replace item 2 in place"` |
| `remove` | `<target> <position>` | `owrap todo remove myproject 2` |
| `clear` | `[<target>]` | `owrap todo clear myproject` |
| `done` | `<target> <position|next|"<phrase>">` | `owrap todo done myproject next` |
| `get` | `[<target> [<position|all>]]` | `owrap todo get myproject 1` |


### `owrap update`

| Action | Usage | Example |
|---|---|---|
| `do` | `<new_path> [--dry-run] [--migrate]` | `owrap update do /mnt/new_home` |


### `owrap updr`

| Action | Usage | Example |
|---|---|---|
| `start` | `[<subproject>] [--ctx]` | `owrap updr start` |
| `done` | `[--error <reason>]` | `owrap updr done` |
| `add` | `<path> [path...] [--note <text>]` | `owrap updr add owrap` |
| `get` | `[memory]` | `owrap updr get` |
| `wait` | `<job_id> [<timeout>]` | `owrap updr wait 7f67b3760d` |


### `owrap worktree`

| Action | Usage | Example |
|---|---|---|
| `add` | `[<name>] [<ref>]` | `owrap worktree add` |
| `done` | `[<sid>] [<repo_id>] [apply]` | `owrap worktree done` |
| `clear` | `[<sid>] [apply]` | `owrap worktree clear` |
<!-- END GENERATED: full command reference -->
