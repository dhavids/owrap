# owrap

Three CLI helpers (`oread`, `orun`, `oexec`) wrapping `opencode run` for the planner/executor MARL research workflow. owrap is an opencode wrapper — a convenience layer for the research management system.

## Structure

```
owrap/
├── owrap/          # Python package
│   ├── manager.py  # Server lifecycle + task tracking
│   ├── read.py     # oread runner
│   ├── run_cmd.py  # orun runner
│   ├── exec.py     # oexec runner
│   ├── runner.py   # CLI entry point
│   ├── base.py     # BaseRunner ABC
│   ├── notify.py   # Completion notifier
│   └── utils/      # logger, terminal, paths
├── docs/           # Local todo.md (used when no research config)
├── templates/      # Starter files for new projects
├── tests/          # Unit tests
└── README.md
```

## Components

| Component | File | Role |
|---|---|---|
| Server manager | `owrap/manager.py` | Persistent opencode server lifecycle (start/stop/state), task tracking, log cleanup |
| File reader | `owrap/read.py` | `oread` — structured speed-read via opencode |
| Task dispatcher | `owrap/run_cmd.py` | `orun` — dispatch tasks via `--task --do` or file-based task files |
| Plan executor | `owrap/exec.py` | `oexec` — execute active research plan |
| Notifier | `owrap/notify.py` | Completion notifications on task end |
| CLI wrapper | `owrap/runner.py` | Subparser CLI routing for all commands |
| Base runner | `owrap/base.py` | `BaseRunner` ABC for subcommand runners |
| Utilities | `owrap/utils/` | Stripped `logger.py`, `terminal.py`, `paths.py` (no MARL/ROS deps) |

## Requirements

- `opencode` CLI
- `inotifywait` (for `owait` shim)

## Shim Locations

| Shim | Location |
|---|---|
| `oread` | `~/bin/oread` |
| `orun` | `~/bin/orun` |
| `oexec` | `~/bin/oexec` |
| `owait` | `~/bin/owait` |

## Usage

```bash
# Quick file read
oread -f path/to/file.py -s -d "what does this function do"

# Dispatch a short task
orun --msg "add a print statement to foo.py"

# Dispatch a file-based task (write task to input.md first)
orun

# Execute the active research plan
oexec

# Pass --dangerously-skip-permissions to opencode
oread -f file.py -a
orun --msg "do something" -a
oexec -a
```
