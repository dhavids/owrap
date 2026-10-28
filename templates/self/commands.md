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
| `owrap start project` | Start a targeted project session |
| `owrap add project` | Select or create a regular subproject, or create scratch notes |
| `owrap set project` | Return the current project session to main, select an existing subproject, or set its risk level |
| `owrap add session` | Create a child session with inherited target, or an independent one via `temp` |
| `owrap done session` | Preview or merge child context |
| `owrap attach session` | Bind this window to a session |
| `owrap refresh session` | Refresh session context and orientation |
| `owrap stop session` | Stop the current session (reversible via `owrap session restore`) |
| `owrap do stat` | Show sessions, types, recent tasks, live stages, and server status |
| `owrap add worktree` | Create a child session with Git worktrees |
| `owrap done worktree` | Preview or merge branch code |
| `owrap clear worktree` | Remove merged branch worktrees |


## Record and context commands

| Command | Effect |
|---|---|
| `owrap start ctx` | Queue a session context update |
| `owrap get decision` | List decisions for a project/repository/session target |
| `owrap clear project` | Delete the active target's disposable scratch notes |
| `owrap get project` | Read project/subproject goals and decisions, or report identity |
| `owrap add proposal` | File a change request for owrap's tooling |
| `owrap get proposal` | List open owrap tooling proposals, or print the template |
| `owrap do proposal` | Work a proposal (owrap session) or add a note (any) |
| `owrap do sync` | Stage and merge workspace instructions |
| `owrap add todo` | Add a goal to a project/repository/session target |
| `owrap get todo` | List goals for a project/repository/session target |
| `owrap start updr` | Queue durable record updates, optionally with context |


## Dispatch commands

| Command | Effect |
|---|---|
| `owrap start exec` | Execute the active session plan |
| `owrap start fallback` | Run a direct fallback task or plan |
| `owrap start read` | Read a file or list a directory |
| `owrap wait session` | Wait for queued input to clear |
| `owrap start task` | Run one inline task, or dispatch a task file |


## Server management

| Command | Effect |
|---|---|
| `owrap start / stop / restart daemon` | Manage the background daemon process directly |
| `owrap get daemon` | Report whether the daemon is running (and its pid) |
| `owrap kill daemon` | Kill all running tasks, pool servers, and the daemon itself (optionally scoped to one session) |
| `owrap clean daemon` | Remove stale session/context/server-log files |
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

<!-- BEGIN GENERATED: config table (templates/build.py) -->
| Key | Type | Default | Description |
|---|---|---|---|
| `owrap_runner_enabled` | bool | `true` | Runner on/off switch. When `false`, dispatch tooling (`owrap read`/`exec`/`agent`/`task`, or `owrap fallback start`) is disabled and planner works directly. |
| `owrap_context_manager_enabled` | bool | `true` | Gates the context-manager pipeline (Update Context/Update Protocol dispatch, including PreCompact), independent of the runner switch above. |
| `permit_bypass_all` | bool | `false` | When `true`, `owrap p` auto-approves every Bash/Write/Edit call with no rule matching. Explicit opt-in only -- never implied by the runner switch. |
| `runner_allow_all` | bool | `true` | Always pass `--dangerously-skip-permissions` to opencode dispatches. |
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
| `ctx_check_interval_s` | float | `900` | Seconds between the daemon's background checks for an attached window's unprocessed transcript diff -- an auto-dispatch still only fires once the excerpt clears `CTX_MIN_CHARS` (5k) and this window's own 5-min cooldown, and otherwise follows a 15m/1h/2h schedule that cycles back to 15m after repeated opencode-down failures. |
| `stale_detach_check_interval_s` | float | `86400` | Seconds between the daemon's sweeps for an attached window gone stale -- idle, or transcript-less, for `STALE_WINDOW_DAYS` (7 days). Only detaches the pointer; the session itself re-attaches normally later. |
| `runner_model` | string | — | Model for regular runner dispatch (`owrap task start`/`owrap exec start`). |
| `context_manager_model` | string | — | Model for context-manager tasks (Update Context/Update Protocol dispatch). |
| `context_fallback_model` | string | — | Fallback model when `context_manager_model` isn't set. |
| `daemon_default_model` | string | — | Reserved for the daemon; not currently consumed (the daemon is pure lifecycle management, no model calls). |
| `msg_kill_s` / `task_kill_s` / `exec_kill_s` | int | `30`/`60`/`120` | No output kill timeouts for msg, task, exec jobs. |
| `stall_notify_s` | int | `120` | Seconds before notification for a stalled job. |
| `watchdog_poll_s` | int | `10` | Watchdog polling interval. |
| `expected_duration_*` | int | varies | Expected duration thresholds for msg/read/task/exec. |
<!-- END GENERATED: config table -->


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
| `start` | `<data> [--id <id>] [--timeout <s>] [--clear]` | `owrap start agent 'review owrap/cli.py for dead code'` |
| `get` | `<task_id>` | `owrap get agent a_1234` |
| `clear` | `` | `owrap clear agent` |


### `owrap backup`

| Action | Usage | Example |
|---|---|---|
| `add` | `[<target>]` | `owrap add backup` |
| `get` | `[<target>] [<timestamp>]` | `owrap get backup` |
| `restore` | `[<target>] <timestamp>` | `owrap restore backup myproject latest` |
| `remove` | `[<target>] [<which>]` | `owrap remove backup myproject` |


### `owrap branch`

| Action | Usage | Example |
|---|---|---|
| `add` | `<project_id> <branch_id> <parent_id> <repository_id> <branch_ref>` | `owrap add branch myproject feature-x main myrepo feature/x` |
| `done` | `<project_id> <branch_id> [apply]` | `owrap done branch myproject feature-x` |


### `owrap ctx`

| Action | Usage | Example |
|---|---|---|
| `start` | `` | `owrap start ctx` |
| `template` | `[subproject]` | `owrap template ctx` |
| `get` | `[template [subproject]|hook]` | `owrap get ctx` |
| `done` | `[--error <reason>]` | `owrap done ctx` |
| `add` | `<path> [path...] [--note <text>]` | `owrap add ctx owrap` |
| `wait` | `<job_id> [<timeout>]` | `owrap wait ctx 7f67b3760d` |


### `owrap daemon`

| Action | Usage | Example |
|---|---|---|
| `start` | `` | `owrap start daemon` |
| `stop` | `` | `owrap stop daemon` |
| `restart` | `` | `owrap restart daemon` |
| `get` | `` | `owrap get daemon` |
| `kill` | `[<session_id>]` | `owrap kill daemon` |
| `clean` | `[<session_id>]` | `owrap clean daemon` |


### `owrap decision`

| Action | Usage | Example |
|---|---|---|
| `add` | `<target> "<text>"` | `owrap add decision myproject "Keep the dev/live split"` |
| `remove` | `<target> <position>` | `owrap remove decision myproject 2` |
| `clear` | `[<target>]` | `owrap clear decision myproject` |
| `get` | `[<target> [<position|all>]]` | `owrap get decision myproject 1` |


### `owrap exec`

| Action | Usage | Example |
|---|---|---|
| `start` | `[--timeout <s>] [--no-watchdog]` | `owrap start exec` |
| `get` | `<task_id>` | `owrap get exec abc123` |


### `owrap fallback`

| Action | Usage | Example |
|---|---|---|
| `start` | `<path>` | `owrap start fallback plan.md` |
| `done` | `<task|exec>` | `owrap done fallback task` |
| `get` | `<task|exec>` | `owrap get fallback task` |


### `owrap model`

| Action | Usage | Example |
|---|---|---|
| `set` | `<slot> <query> [workspace]` | `owrap set model runner haiku` |


### `owrap permit`

| Action | Usage | Example |
|---|---|---|
| `set` | `<on|off> | <name> <on|off>` | `owrap set permit on` |
| `get` | `[<workspace>]` | `owrap get permit` |


### `owrap project`

| Action | Usage | Example |
|---|---|---|
| `start` | `[<id>]` | `owrap start project myproject` |
| `update` | `<old-id> <new-id>` | `owrap update project myproject renamed-project` |
| `add` | `<name> [force]` | `owrap add project docs` |
| `clear` | `scratch` | `owrap clear project scratch` |
| `set` | `[<name>|risk <low|high>]` | `owrap set project` |
| `get` | `[main|subs|sub <name>|scratch [path]|name|path|risk]` | `owrap get project` |


### `owrap proposal`

| Action | Usage | Example |
|---|---|---|
| `add` | `<file|-> [--force]` | `owrap add proposal proposal.md` |
| `get` | `[template|all|<id>]` | `owrap get proposal` |
| `do` | `<id> <claim|done|reject|note> [<text>]` | `owrap do proposal my-proposal claim` |


### `owrap read`

| Action | Usage | Example |
|---|---|---|
| `start` | `<file> [--summarise] [--details <text>] [--grep <pattern>] [--id <id>]` | `owrap start read owrap/cli.py` |
| `get` | `<task_id>` | `owrap get read r_1234` |


### `owrap repository`

| Action | Usage | Example |
|---|---|---|
| `add` | `<repo_id> [checkout]` | `owrap add repository myrepo` |
| `update` | `<old_id> <new_id>` | `owrap update repository myrepo renamed-repo` |
| `remove` | `<repo_id>` | `owrap remove repository myrepo` |
| `attach` | `<repo_id> <project_id>` | `owrap attach repository myrepo myproject` |
| `detach` | `<repo_id> <project_id>` | `owrap detach repository myrepo myproject` |


### `owrap self`

| Action | Usage | Example |
|---|---|---|
| `get` | `[home|opencode [reason]|config [workspace]|plan|input|output <kind>|runtime [history]|history] [--count <n>] [--tail <n>] [-g <pattern>] [--sid <id>]` | `owrap get self` |


### `owrap session`

| Action | Usage | Example |
|---|---|---|
| `add` | `[temp] [<label>]` | `owrap add session` |
| `done` | `[<sid>] [apply]` | `owrap done session` |
| `restore` | `<sid>` | `owrap restore session abc123` |
| `wait` | `[<timeout>]` | `owrap wait session` |
| `attach` | `<target>` | `owrap attach session abc123` |
| `refresh` | `` | `owrap refresh session` |
| `stop` | `[force]` | `owrap stop session` |


### `owrap setup`

| Action | Usage | Example |
|---|---|---|
| `do` | `<path> | --name <n> --workspace <path> [options]` | `owrap do setup /path/to/workspace` |


### `owrap stat`

| Action | Usage | Example |
|---|---|---|
| `do` | `` | `owrap do stat` |
| `get` | `<session_id>` | `owrap get stat abc123` |


### `owrap subproject`

| Action | Usage | Example |
|---|---|---|
| `update` | `<project_id> <old_id> <new_id>` | `owrap update subproject myproject docs renamed-docs` |
| `remove` | `<project_id> <sub_id>` | `owrap remove subproject myproject docs` |


### `owrap sync`

| Action | Usage | Example |
|---|---|---|
| `do` | `` | `owrap do sync` |


### `owrap task`

| Action | Usage | Example |
|---|---|---|
| `start` | `[--msg <text>] [--id <id>] [--input <path>]` | `owrap start task --msg 'summarise owrap/cli.py'` |
| `done` | `<target> [<session_id>]` | `owrap done task exec` |
| `get` | `<task_id>` | `owrap get task r_1234` |


### `owrap todo`

| Action | Usage | Example |
|---|---|---|
| `add` | `<target> [<position>] "<text>"` | `owrap add todo myproject "Fix the auth redirect bug"` |
| `update` | `<target> <position> "<text>"` | `owrap update todo myproject 2 "Replace item 2 in place"` |
| `remove` | `<target> <position>` | `owrap remove todo myproject 2` |
| `clear` | `[<target>]` | `owrap clear todo myproject` |
| `done` | `<target> <position|next|"<phrase>">` | `owrap done todo myproject next` |
| `get` | `[<target> [<position|all>]]` | `owrap get todo myproject 1` |


### `owrap update`

| Action | Usage | Example |
|---|---|---|
| `do` | `<new_path> [--dry-run] [--migrate]` | `owrap do update /mnt/new_home` |


### `owrap updr`

| Action | Usage | Example |
|---|---|---|
| `start` | `[<subproject>] [--ctx]` | `owrap start updr` |
| `done` | `[--error <reason>]` | `owrap done updr` |
| `add` | `<path> [path...] [--note <text>]` | `owrap add updr owrap` |
| `get` | `[memory]` | `owrap get updr` |
| `wait` | `<job_id> [<timeout>]` | `owrap wait updr 7f67b3760d` |


### `owrap worktree`

| Action | Usage | Example |
|---|---|---|
| `add` | `[<name>] [<ref>]` | `owrap add worktree` |
| `done` | `[<sid>] [<repo_id>] [apply]` | `owrap done worktree` |
| `clear` | `[<sid>] [apply]` | `owrap clear worktree` |
<!-- END GENERATED: full command reference -->
