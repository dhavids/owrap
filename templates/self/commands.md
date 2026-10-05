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
| `owrap stat` | Show sessions, types, tasks, and server status |
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

## Duration defaults

Expected durations and watchdog limits come from workspace configuration.
Check `owrap get config` for current values before changing timeouts.

## Exit codes

`0` means success. Other codes identify infra failure, timeout, crash,
unresponsiveness, or a watchdog termination. Read the dispatch output and
`owrap stat` before redispatching a failed task; rewrite a consumed input file
when its content needs correction.
