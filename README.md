> **Note:** All commands use the `~/bin/` prefix (`~/bin/owrap`, `~/bin/orun`, `~/bin/oread`,
> `~/bin/oexec`, `~/bin/owait`). This is a temporary workaround until a cleaner install
> approach is available that does not require **sudo**. The prefix ensures the commands are
> found regardless of whether `~/bin` is on the shell's PATH.

# owrap

Session-aware bridge between Claude Code (planner) and opencode (executor). Background task dispatch, parallel session isolation, and inotifywait completion notifications.

Use Claude's brain with opencode's muscle.

## What it provides

| Command | Description |
|---|---|
| `~/bin/owrap start [name]` | Start a session: generate ID, start the opencode server, print orientation |
| `~/bin/owrap refresh [name]` | Re-validate a session; re-print orientation |
| `~/bin/owrap restart [name]` | Stop server + clear sessions, then start a fresh session |
| `~/bin/owrap stop` | Kill server + clear all session files |
| `~/bin/owrap end` | End this session only (server keeps running) |
| `~/bin/owrap stat` | Show all active sessions, server liveness, and age |
| `~/bin/owrap cleanup [id]` | Remove stale sessions (>2h or PPID-based); optional partial ID to target one |
| `~/bin/oread -f <file>` | Print file; if >500 lines, summarise via opencode |
| `~/bin/oread -f <dir>` | List directory contents (instant) |
| `~/bin/oread -g <pattern>` | Grep recursively in current directory (instant) |
| `~/bin/oread -g <pattern> -f <path>` | Grep in specific file or directory (instant) |
| `~/bin/oread -f <file> -s` | Summarise file via opencode (foreground, ~10–45s) |
| `~/bin/oread -f <file> -d "..."` | Targeted query on file via opencode; times out after 55s |
| `~/bin/orun --msg "..."` | Single-line task dispatch (foreground) |
| `~/bin/orun` | File task from `input_<id>.md` (auto-background + owait) |
| `~/bin/oexec` | Execute active plan (auto-background + owait) |
| `~/bin/owait run <id>` | Block until a run task completes for session `<id>` |
| `~/bin/owait exec <id>` | Block until exec completes for session `<id>` |
| `~/bin/owait read <id>` | Block until a read completes for session `<id>` |

## Requirements

- `claude code` VSCode or CLI
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
pip install -e .        # editable install — source changes take effect immediately
python3 setup.py        # installs shims to ~/bin/, checks deps, optionally adds ~/bin to PATH
```

`setup.py` checks all dependencies and installs shims (`oread`, `orun`, `oexec`, `owait`, `owrap`) to `~/bin/` with the correct `OWRAP_ROOT` path baked in. It prints install hints for anything missing — it never installs dependencies itself. Make sure `~/bin/` is on your `$PATH`.

## Updating

### Shims (after every `git pull`)

Python source is live via the editable install — only the shims need re-writing:

```bash
git pull
python3 update.py
```

`update.py` re-installs all 5 shims from `bin/` templates into `~/bin/`, substituting the correct `OWRAP_ROOT` and Python paths. The running server does not need to be restarted.

## Getting Started

After running `python3 setup.py`, tell Claude Code to start a session:

> Run this command in bash and execute the instructions: `~/bin/owrap setup <project_root> [research_folder]`

For example:
> Run this command in bash and execute the instructions: `~/bin/owrap setup /home/user/myproject /home/user/myproject/docs/research`

Claude will run `~/bin/owrap setup`, read the printed instructions, and set up your `CLAUDE.md`,
`AGENTS.md`, `self.md`, and `settings.json` for the project. After that, tell it:

> Run this command in bash: `~/bin/owrap start <research_name>`

Claude will orient itself and be ready to plan.

## Updating Planner Files

When owrap templates change, the project files already installed in your research project may fall behind. To check what needs updating:

```bash
~/bin/owrap setup --update
```

This prints, for each file:
- **EXISTS** — compare with the template and merge any sections present in the template but missing from the installed file
- **MISSING** — copy the template to the destination and fill in placeholders

It also prints the resolved values for every placeholder (`<project_root>`, `<research_root>`, `<owrap_docs>`) and example expanded `Edit`/`Read` rules so you can verify `settings.json` has the correct absolute paths.

**To update the planner files, tell Claude:**

> Run this command in bash and execute the instructions: `~/bin/owrap setup --update`

Claude will compare each installed file against the corresponding template and merge any missing sections without overwriting content that already exists or is more detailed than the template.

**Merge rule** (applied by the planner):
- Sections present in template but missing from installed file → add them
- Sections present in installed file but absent from template → leave untouched
- Never reorder, remove, or overwrite existing content

## Limits and Timeouts

| Limit | Value | Notes |
|---|---|---|
| `orun --msg` max length | 1024 chars | Longer tasks should use file-based `orun` via `input_<id>.md` |
| `oread -d` query timeout | 55 seconds | Partial output printed on expiry; try `-s` for very large files |
| `oread` auto-summarise threshold | 500 lines | Files above this line count are forwarded to opencode for summary |

## `owrap setup` path resolution

When `project_root` or `research_folder` are not passed as arguments to `owrap setup`, owrap reads them from `configs/owrap.json`. Resolution order:

1. Stored value as absolute path — used if it is a valid directory
2. Stored value relative to `~` — used if that resolves to a valid directory
3. `~` (home directory) — last resort fallback

This means `owrap setup` with no arguments is safe to run at any time: it will re-read the stored config and display the current file status and settings.

## Configuration

Copy `templates/config.json` to `configs/owrap.json` and edit. The file should be gitignored.

| Key | Type | Description |
|---|---|---|
| `default_research` | string | Default project name when no research is specified (e.g. `my_project`) |
| `project_root` | string | Path to the project root (where `CLAUDE.md`, `AGENTS.md`, `.claude/` live) |
| `research_root` | string | Path to the research folder (where `self.md` lives; often `<project_root>/docs/research`) |
| `allow_all` | bool | Always pass `--dangerously-skip-permissions` to opencode |

```json
{
  "default_research": "my_project",
  "project_root": "/home/user/my_project",
  "research_root": "/home/user/my_project/docs/research",
  "allow_all": false
}
```

## Session Workflow

Every opencode session begins with `owrap start`. This generates a session ID, starts or attaches to the opencode server, and writes a session file at `~/.owrap/sessions/${CLAUDE_CODE_SESSION_ID}.session` — keyed to the Claude Code window's stable session ID for automatic isolation across concurrent windows.

```bash
~/bin/owrap setup /path/to/research   # optional: configure research_root, install shims, check templates
~/bin/owrap start                     # begin session — falls back to default_research from config
~/bin/owrap start my_project          # begin session with a specific research project
# ... do work with ~/bin/oread, ~/bin/orun, ~/bin/oexec ...
~/bin/owrap stop                      # end session — deletes the session file
~/bin/owrap restart                   # stop + fresh start in one step (uses default_research from config)
~/bin/owrap restart my_project        # stop + fresh start with a specific research project
```

`~/bin/owrap refresh [name]` re-validates the session (re-starts the server if it died) and re-prints the orientation block. Use it if you suspect the server has gone away. If no name is given it falls back to `default_research` from `configs/owrap.json`.

`~/bin/owrap restart [name]` is equivalent to `stop` followed by `start` — useful when you want a clean session ID after a crash or stale state. Research name falls back to `default_research` from config if omitted.

All runtime paths are session-scoped: log files, task files, and output files are suffixed with the session ID. Concurrent sessions from different shell PIDs are fully isolated — they share the same server but have independent task queues and logs.

## Commands Reference

| Command | What it does |
|---|---|
| `~/bin/owrap start [name]` | Start session: generate ID, start server, print orientation |
| `~/bin/owrap refresh [name]` | Re-validate session; re-print orientation |
| `~/bin/owrap restart [name]` | Stop server + clear sessions, then start a fresh session |
| `~/bin/owrap stop` | Kill server + clear all session files |
| `~/bin/owrap end` | End this session only (server keeps running) |
| `~/bin/owrap stat` | Show all active sessions, server liveness, and age |
| `~/bin/owrap cleanup [id]` | Remove stale sessions; optional partial ID to target one |
| `~/bin/oread -f <file>` | Print file; if >500 lines, summarise via opencode instead |
| `~/bin/oread -f <dir>` | List directory contents (instant, replaces ls) |
| `~/bin/oread -g <pattern>` | Grep recursively in cwd (instant, replaces grep) |
| `~/bin/oread -g <pattern> -f <path>` | Grep in specific file or directory (instant) |
| `~/bin/oread -f <file> -s` | Summarise file via opencode (foreground) |
| `~/bin/oread -f <file> -d "..."` | Targeted query; 55s timeout with partial output on expiry |
| `~/bin/orun --msg "..."` | Single-line task dispatch, max 1024 chars (foreground) |
| `~/bin/orun` | File task from `input_<id>.md` (auto-background + owait) |
| `~/bin/oexec` | Execute active plan (auto-background + owait) |
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
