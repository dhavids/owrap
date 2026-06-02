> **Note:** All commands use the `~/bin/` prefix (`~/bin/owrap`, `~/bin/orun`, `~/bin/oread`,
> `~/bin/oexec`, `~/bin/owait`). This is a temporary workaround until a cleaner install
> approach is available that does not require **sudo**. The prefix ensures the commands are
> found regardless of whether `~/bin` is on the shell's PATH.

# owrap

Session-aware bridge between Claude Code (planner) and opencode (executor). Background task dispatch, parallel session isolation, and Python mtime-polling completion notifications.

Use Claude's brain with opencode's muscle.

## Requirements

- `claude code` VSCode or CLI
- `opencode` CLI
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
| `oread -d` / `-s` timeout | 55–180s (scales with file size) | Partial output printed on expiry; use `-t <secs>` to extend |
| `oread` auto-summarise threshold | 8000 chars | Files above this character count are forwarded to opencode for summary |

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
| `oread_always` | bool | When `true`, all file reads must go through `oread` — direct `cat`/`ls`/`grep` denied by permissions. When `false`, direct `Read` is also permitted (default: `true`) |
| `use_multiple_servers` | bool | Enable multi-server mode; each new session may start its own server (default: `false`) |
| `max_servers` | int | Maximum number of concurrent opencode servers when `use_multiple_servers` is true (default: `1`) |

```json
{
  "default_research": "my_project",
  "project_root": "/home/user",
  "research_root": "/home/user/my_project/docs/research",
  "allow_all": false,
  "oread_always": true,
  "use_multiple_servers": false,
  "max_servers": 1
}
```

## Prompt Styles

`oread -s` (summarise) and `oread -d` (query) use a prompt style that shapes the output format. The style is auto-detected from the file extension; override with `-p <style>`.

Run `~/bin/oread --list-styles` to see styles and extension defaults at any time.

| Style | Output |
|---|---|
| `terse` | Max 5 bullets, most important facts only. Default for `.md`, `.txt`, `.rst`. |
| `code` | Purpose, key classes/functions with one-line descriptions, side-effects. 20 lines max. Default for `.py`, `.sh`, `.js`, `.ts`, `.cpp`, `.c`, `.go`, `.rs`. |
| `structured` | `## Purpose` / `## Key Parts` / `## Watch-outs` headers. 25 lines max. Default for `.yaml`, `.yml`, `.json`, `.toml`, `.ini`, `.cfg`. |
| `bullets` | Bullets only — what, why, how, gotchas. 10 bullets max. Default for `.csv`, `.log`, `.tsv`. |
| `exec` | Single plain-prose paragraph, 4–6 sentences. |
| `default` | Direct answer, configurable line limit. |
| `deep` | Strategic read: flags None/stub values, config mutations, disabled features, numeric inconsistencies. 30 lines max. |

Files not matching a known extension default to `terse`.

## Session Workflow

Every opencode session begins with `owrap start`. This generates a session ID, starts or attaches to the opencode server, and writes a session file at `~/.owrap/sessions/${CLAUDE_CODE_SESSION_ID}.session` — keyed to the Claude Code window's stable session ID for automatic isolation across concurrent windows.

```bash
~/bin/owrap setup /path/to/research   # optional: configure research_root, install shims, check templates
~/bin/owrap start                     # begin session — falls back to default_research from config
~/bin/owrap start my_project          # begin session with a specific research project
# ... do work with ~/bin/oread, ~/bin/orun, ~/bin/oexec ...
~/bin/owrap stop                      # end current session; kills server only if no other sessions are active
~/bin/owrap stop --force              # kill server + clear all sessions unconditionally
~/bin/owrap restart                   # end current session + start fresh (server preserved if others active)
~/bin/owrap restart my_project        # restart with a specific research project
~/bin/owrap restart --force           # kill server + clear all sessions, then start fresh
```

`~/bin/owrap refresh [name]` re-validates the session (re-starts the server if it died) and re-prints the orientation block. Use it if you suspect the server has gone away, or after context compaction. If no name is given, the research stored in the session file is used; only falls back to `default_research` from `configs/owrap.json` if the session file has no research recorded.

`~/bin/owrap restart [name]` ends the current session and starts a fresh one. Without `--force`, the server is kept running if other sessions are active. With `--force`, the server is killed and all sessions are cleared before starting.

All runtime paths are session-scoped: log files, task files, and output files are suffixed with the session ID. Concurrent sessions from different shell PIDs are fully isolated — they share the same server but have independent task queues and logs.

## Commands Reference

| Command | What it does |
|---|---|
| `~/bin/owrap start [name]` | Start session: generate ID, start server, print orientation |
| `~/bin/owrap refresh [name]` | Re-validate session; re-print orientation |
| `~/bin/owrap restart [name]` | End current session + start fresh; `--force` kills server first |
| `~/bin/owrap stop` | End current session (server kept running if others active); `--force` kills server + clears all |
| `~/bin/owrap end` | End this session only (server keeps running) |
| `~/bin/owrap stat` | Show all active sessions, server liveness, and age |
| `~/bin/owrap cleanup [id]` | Remove stale sessions; optional partial ID to target one |
| `~/bin/owrap finish <target>` | Kill a running job by target (exec, task1, task2, msg1, …) — sends SIGTERM to its PID |
| `~/bin/owrap setup [project_root] [research_folder]` | Configure `configs/owrap.json`, install templates, print FILES/SETTINGS instructions |
| `~/bin/oread -f <file>` | Print file; if >8000 chars, summarise via opencode instead |
| `~/bin/oread -f <file> -v` | Full cat bypassing the 8000-char summarise threshold (instant) |
| `~/bin/oread -f <dir>` | List directory contents (instant, replaces ls) |
| `~/bin/oread -g <pattern>` | Grep recursively in cwd (instant, replaces grep) |
| `~/bin/oread -g <pattern> -f <path>` | Grep in specific file or directory (instant) |
| `~/bin/oread -f <file> -s` | Summarise file via opencode; style auto-detected by extension (foreground) |
| `~/bin/oread -f <file> -s -p <style>` | Summarise with explicit style: `default`, `terse`, `structured`, `code`, `exec`, `bullets`, `deep` |
| `~/bin/oread --list-styles` | List all prompt styles and file-extension auto-detect defaults |
| `~/bin/oread -f <file> -d "..."` | Targeted query; timeout scales 55–180s with file size; partial output on expiry |
| `~/bin/oread -f <file> -d "..." -t <secs>` | Targeted query with custom timeout in seconds |
| `~/bin/oread -i <id> -f <file>` | Tag read output with `[r:<id>]` for parallel tracking |
| `~/bin/orun --msg "..."` | Inline task dispatch, ≤1024 chars (foreground); --msg - reads from stdin for multiline |
| `~/bin/orun -i <id> --msg "..."` | Parallel tagged msg: output prefixed `[m:<id>]`, waitable by ID |
| `~/bin/orun --msg "..." -t <secs>` | Custom timeout for `--msg` (default: 180s) |
| `~/bin/orun` | File task from `input_<id>.md` (auto-background + owait) |
| `~/bin/orun --input <path>` | File task from a custom input path instead of `input_<id>.md` |
| `~/bin/oexec` | Execute active plan (auto-background + owait) |
| `~/bin/owait run <id>` | Block until a run task completes for session `<id>` |
| `~/bin/owait exec <id>` | Block until exec completes for session `<id>` |
| `~/bin/owait read <id>` | Block until a read completes for session `<id>` |
| `~/bin/owait msg <id>` | Block until a specific `--msg` (dispatched with `-i <id>`) completes |
| `~/bin/owait input` | Block until `input_<id>.md` is cleared (task picked up); prints `input clear` |

## Parallel Task Dispatch

`~/bin/orun` (without `--msg`) reads a task from a staging file and auto-backgrounds the opencode process. Multiple tasks can be dispatched in parallel:

```
write task A → input_<id>.md
~/bin/orun                          ← picks up, creates task1.md, clears input, backgrounds
~/bin/owait input                   ← blocks until input_<id>.md is cleared; prints "input clear"
write task B → input_<id>.md
~/bin/orun                          ← creates task2.md, clears, backgrounds
~/bin/owait input                   ← blocks until input_<id>.md is cleared; prints "input clear"
# task1 and task2 now running in parallel
~/bin/owait run <id>                ← unblocks on first completion
~/bin/owait run <id>                ← unblocks on second
```

Use `--fg` on `~/bin/orun` or `~/bin/oexec` to force foreground execution instead of auto-backgrounding.

To cancel a running job before it completes, use `~/bin/owrap finish <target>`, where target is `exec`, `task`, `task1`, `task2`, `msg`, `msg1`, etc. This sends SIGTERM to the job's PID (read from the sentinel file in `~/.owrap/running/`). Exit code 0 if at least one job was signalled; 1 if no matching job was found.
