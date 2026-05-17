> **Note:** All commands use the `~/bin/` prefix (`~/bin/owrap`, `~/bin/orun`, `~/bin/oread`,
> `~/bin/oexec`, `~/bin/owait`). This is a temporary workaround until a cleaner install
> approach is available that does not require sudo. The prefix ensures the commands are
> found regardless of whether `~/bin` is on the shell's PATH.

# owrap

Session-aware CLI wrapper for opencode. Background task dispatch, parallel session isolation, and inotifywait completion notifications.

## What it provides

| Command | Description |
|---|---|
| `~/bin/owrap start` | Start a session: generate ID, start the opencode server, print orientation |
| `~/bin/owrap refresh` | Re-validate a session; re-print orientation |
| `~/bin/owrap stop` | End a session: delete the session file |
| `~/bin/oread -f <file> [-s] [-d "..."]` | Read/query a file via opencode (foreground) |
| `~/bin/orun --msg "..."` | Single-line task dispatch (foreground) |
| `~/bin/orun` | File-based task dispatch (auto-background + wait for completion) |
| `~/bin/oexec` | Execute an active research plan (auto-background + wait for completion) |
| `~/bin/owait run <id>` | Block until a run task completes for session `<id>` |
| `~/bin/owait exec <id>` | Block until exec completes for session `<id>` |
| `~/bin/owait read <id>` | Block until a read completes for session `<id>` |

## Requirements

- `opencode` CLI
- `inotify-tools` (`inotifywait`) — Linux only
- Python >= 3.10

## Prerequisites

### Node.js and npm

Both Claude Code and opencode are installed via npm. Install Node.js (which includes npm) using nvm (recommended):

```bash
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash
source ~/.bashrc   # or ~/.zshrc
nvm install --lts
nvm use --lts
```

Or via apt:

```bash
sudo apt update && sudo apt install -y nodejs npm
```

Verify: `node --version && npm --version`

### Claude Code

```bash
npm install -g @anthropic-ai/claude-code
```

### opencode

```bash
npm i -g opencode-ai
```

Verify: `opencode --version`

### inotify-tools (Linux only)

```bash
sudo apt install inotify-tools -y
```

### Python >= 3.10

```bash
python3 --version   # check existing version
```

If needed: `sudo apt install python3.10` or use pyenv.

## Installation

```bash
git clone https://github.com/dhavids/owrap.git
cd owrap
python setup.py
```

`setup.py` checks all dependencies and installs shims (`oread`, `orun`, `oexec`, `owait`, `owrap`) to `~/bin/` with the correct `OWRAP_ROOT` path baked in. It prints install hints for anything missing — it never installs dependencies itself. Make sure `~/bin/` is on your `$PATH`.

## Getting Started

After running `python3 setup.py`, tell Claude Code to start a session:

> Run this command in bash and execute the instructions: `~/bin/owrap setup <your_research_folder>`

For example:
> Run this command in bash and execute the instructions: `~/bin/owrap setup /home/user/myproject/research`

Claude will run `~/bin/owrap setup`, read the printed instructions, and set up your `CLAUDE.md`,
`AGENTS.md`, `self.md`, and `settings.json` for the project. After that, tell it:

> Run this command in bash: `~/bin/owrap start <research_name>`

Claude will orient itself and be ready to plan.

## Configuration

Copy `templates/config.json` to `configs/owrap.json` and edit. The file should be gitignored.

| Key | Type | Description |
|---|---|---|
| `default_research` | string | Default project name when no research is specified (e.g. `my_project`) |
| `research_root` | string | Path to the `docs/research` folder |
| `allow_all` | bool | Always pass `--dangerously-skip-permissions` to opencode |

```json
{
  "default_research": "my_project",
  "research_root": "/home/user/my_project/docs/research",
  "allow_all": false
}
```

## Session Workflow

Every opencode session begins with `owrap start`. This generates a session ID, starts or attaches to the opencode server, and writes a session file at `/tmp/owrap/$PPID.session` — keyed to the invoking shell's PID for automatic isolation across concurrent sessions.

```bash
~/bin/owrap setup /path/to/research   # optional: configure research_root, install shims, check templates
~/bin/owrap start                     # begin session — prints orientation with session ID and command patterns
~/bin/owrap start my_project          # begin session with a specific research project
# ... do work with ~/bin/oread, ~/bin/orun, ~/bin/oexec ...
~/bin/owrap stop                      # end session — deletes the session file
```

`~/bin/owrap refresh` re-validates the session (re-starts the server if it died) and re-prints the orientation block. Use it if you suspect the server has gone away.

All runtime paths are session-scoped: log files, task files, and output files are suffixed with the session ID. Concurrent sessions from different shell PIDs are fully isolated — they share the same server but have independent task queues and logs.

## Commands Reference

| Command | What it does |
|---|---|
| `~/bin/owrap start` | Start session: generate ID, start server, print orientation |
| `~/bin/owrap refresh` | Re-validate session; re-print orientation |
| `~/bin/owrap stop` | End session: delete session file |
| `~/bin/oread -f <file> [-s] [-d "..."]` | Read/query a file via opencode (foreground) |
| `~/bin/orun --msg "..."` | Single-line task dispatch (foreground) |
| `~/bin/orun` | File task from `input_<id>.md` (auto-background + wait) |
| `~/bin/oexec` | Execute active plan (auto-background + wait) |
| `~/bin/owait run <id>` | Block until a run task completes for session `<id>` |
| `~/bin/owait exec <id>` | Block until exec completes for session `<id>` |
| `~/bin/owait read <id>` | Block until a read completes for session `<id>` |

## Parallel Task Dispatch

`~/bin/orun` (without `--msg`) reads a task from a staging file and auto-backgrounds the opencode process. Multiple tasks can be dispatched in parallel:

```
write task A → input_<id>.md
~/bin/orun                          ← picks up, creates task1.md, clears input, backgrounds
[wait for input_<id>.md to clear]
write task B → input_<id>.md
~/bin/orun                          ← creates task2.md, clears, backgrounds
[wait for input_<id>.md to clear]
# task1 and task2 now running in parallel
~/bin/owait run <id>                ← unblocks on first completion
~/bin/owait run <id>                ← unblocks on second
```

Use `--fg` on `~/bin/orun` or `~/bin/oexec` to force foreground execution instead of auto-backgrounding.

## Repository Structure

```
owrap/
├── bin/
│   ├── oexec
│   ├── oread
│   ├── orun
│   ├── owait
│   └── owrap
├── docs/
│   └── todo.md
├── .gitignore
├── owrap/
│   ├── base.py
│   ├── exec.py
│   ├── __init__.py
│   ├── manager.py
│   ├── read.py
│   ├── refresh.py
│   ├── run_cmd.py
│   ├── runner.py
│   ├── start.py
│   ├── stop.py
│   └── utils/
│       ├── __init__.py
│       ├── logger.py
│       ├── paths.py
│       └── terminal.py
├── README.md
├── setup.py
├── templates/
│   ├── agents.md
│   ├── claude.md
│   ├── config.json
│   ├── exec/
│   │   └── log.md
│   ├── plan.md
│   ├── run/
│   │   └── log.md
│   ├── self.md
│   ├── settings.json
│   └── todo.md
└── tests/
    ├── __init__.py
    ├── test_exec.py
    ├── test_manager.py
    ├── test_read.py
    └── test_run.py
```
