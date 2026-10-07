# Commands

Use `owrap <command> -h` for exact options. Commands below describe the
current session model; existing research and area forms remain available
only during migration.

## Session commands

| Command | Effect |
|---|---|
| `owrap start --project <id> [--subproject <id>]` | Start a targeted project session |
| `owrap start --repository <id>` | Start a repository-only session |
| `owrap main` | Return the current project session to its main record |
| `owrap sub <id> [-f]` | Select or create a regular subproject |
| `owrap subs` | List the current project's subprojects |
| `owrap spawn [name]` | Create a child session with inherited target |
| `owrap temp [name]` | Create an independent session |
| `owrap branch [name] [--ref <ref>]` | Create a child session with Git worktrees |
| `owrap branch merge [--session <id>] [--repo <id>] [--apply]` | Preview or merge branch code |
| `owrap collapse [--session <id>] [--apply]` | Preview or merge child context |
| `owrap branch cleanup --session <id> [--apply]` | Remove merged branch worktrees |
| `owrap attach <id>` | Bind this window to a session |
| `owrap refresh` | Refresh session context and orientation |
| `owrap stat` | Show sessions, types, recent tasks, live stages, and server status |
| `owrap get <kind>` | Read the active session's resource |
| `owrap end` | End the current session |


## Record and context commands

| Command | Effect |
|---|---|
| `owrap get project` | Read project or subproject goals and decisions |
| `owrap get memory` | Read associated repository architecture |
| `owrap get todo` | List goals for the active project target |
| `owrap ctx` | Queue a session context update |
| `owrap updr [subproject] [--ctx]` | Queue durable record updates, optionally with context |
| `owrap sync` | Stage and merge workspace instructions |


## Dispatch commands

| Command | Effect |
|---|---|
| `orun --msg <text>` | Run one inline task |
| `orun --input <path>` | Dispatch a task file |
| `oexec` | Execute the active session plan |
| `oread -f <path>` | Read a file or list a directory |
| `owait input` | Wait for input-file dispatch completion |
| `owait run` | Wait for task completion |
| `owrap f <path>` | Run a direct fallback task or plan |


## Server management

Graceful draining: an unresponsive server, or one past `max_requests_per_server`,
stops receiving new work but finishes in-flight requests before being reaped.
The daemon manages the pool — spawns on first pooled dispatch, maintains
`min_servers`, shuts down idle servers past `idle_shutdown_s`.
`owrap killservers [--session <id>]` kills all servers and running tasks.


## Troubleshooting

| Symptom | Action |
|---|---|
| `NO_SERVER` / no server available | `owrap stat` for pool status; `owrap f <path>` bypasses the pool |
| Task/exec times out | Default ceiling 600s; extend with `-t <secs>`; `owrap abort <target>` sends SIGTERM |
| Stalled-job notification | Fires after `stall_notify_s` (default 120s) with no output; an unresponsive server is marked draining |
| Template changes not picked up | Run `owrap sync`, then dispatch the sync task it prints |
| `owrap_runner_enabled: false` | Dispatch tooling disabled, planner works directly — this alone does not grant unrestricted command access (`permit_bypass_all` is separate) |


## Configuration

Base config: `templates/config.json` → copy to `OWRAP_HOME/configs/base.json`.
Check `owrap get config` for live values.

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


## Duration defaults

Expected durations and watchdog limits come from workspace configuration.
Check `owrap get config` for current values before changing timeouts.


## Exit codes

`0` means success. Other codes identify infra failure, timeout, crash,
unresponsiveness, or a watchdog termination. Read the dispatch output and
`owrap stat` before redispatching a failed task; rewrite a consumed input file
when its content needs correction.
