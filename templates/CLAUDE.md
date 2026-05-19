# CLAUDE.md

This file provides guidance to Claude Code when working with this project.

You are always in **--planner** mode unless a different flag is specified.

## Quick Commands

| Flag | Mode | What to do |
|---|---|---|
| `--start <name>` | Planner | Run `~/bin/owrap start <name>` in bash, then proceed as --planner |
| *(none)* or `--planner` | Planner | Design/update plans, add project TODOs |
| `--executor` / `--exec [path]` | Executor | Read plan → execute → mark TODOs `[x]`. Reads from path if given, else `owrap/docs/plan0.md`. |
| `--check` | Planner review | Verify completed TODOs against plan |
| `--agent` | Planner + auto-dispatch | Plan → delegate via ~/bin/oread/~/bin/orun/~/bin/oexec → verify |
| `--analyser` | Analyser + auto-dispatch | Think-only: analysis plan → dispatch → interpret results |
| `--task` | Task executor | Contract-driven task execution |
| `--taskf [path]` | Fallback | Direct opencode run; reads task from path if given, else `owrap/docs/run/tasks/task0.md`; model self-writes output to fixed log paths |
| `--execf [path]` | Fallback | Direct opencode run; reads plan from path if given, else `owrap/docs/plan0.md`; model self-writes exec output |
| `--setup [project_root] [research_folder]` | Setup | Run `~/bin/owrap setup [project_root] [research_folder]` in bash. project_root is where CLAUDE.md/AGENTS.md/.claude/ live; research_folder (optional) is where self.md lives. Then act on the printed FILES and SETTINGS instructions |
| `--refresh` | Refresh | Run `~/bin/owrap refresh` in bash (re-prints orientation), then check CLAUDE.md, AGENTS.md, self.md against templates — merge missing sections if behind, leave unchanged if already more detailed |

**Hire-first rule:** Delegate any non-thinking work via:
- `~/bin/oread -f <file>` — cat a file (instant for <500 lines, else summarises)
- `~/bin/oread -f <dir>` — ls a directory (instant)
- `~/bin/oread -g <pattern>` — grep recursively in current dir (instant)
- `~/bin/oread -g <pattern> -f <path>` — grep in specific file or directory (instant)
- `~/bin/oread -f <file> -s` — summarise via opencode
- `~/bin/oread -f <file> -d "..."` — targeted query via opencode (55s timeout; `-t <s>` to extend)
- **Multiple oreads:** chain with `&&` in ONE foreground Bash call — one combined output, no notifications, no early-read risk. Parallel background (`run_in_background=True` + `-i <id>`) only when true concurrency matters; wait for ALL notifications before reading any output.
- `~/bin/orun --msg "..."` — short inline tasks (foreground)
- `~/bin/orun --msg "..." -t <s>` — same with custom timeout (default: 180s)
- `~/bin/orun` — file-based tasks (auto-background + owait)
- `~/bin/oexec` — multi-step plan execution (auto-background + owait)

**Direct `cat`, `ls`, `grep` are denied by permissions.** Always use `oread` equivalents above.

**All planner tool use is blocked — no exceptions, no prompting.** The Read, Edit, Write, and Bash tools will be denied by permissions. Do not attempt them, not even inside compound commands (e.g. `ls && oread ...` is still a denied `ls`). Do not ask the user for permission to use a tool — it will always be denied and wastes a turn. The only direct operations the planner may perform are writing to `plan_<id>.md`, `self.md`, `CLAUDE.md`, and `## TODO` sections in project files. For everything else: `oread` for reads, `orun` for writes/edits/commands, `oexec` for plan execution. If owrap is unavailable, fall back to `--taskf`/`--execf` — never direct tool use, never user prompting.

**`owrap setup` path resolution:** if `project_root` or `research_folder` are not passed, owrap reads them from `configs/owrap.json`. If the stored value is a valid absolute directory it is used directly; if not, it is tried relative to `~`; if neither exists, `~` is used as fallback.

**Planner fallback rule:** If the planner itself cannot invoke `~/bin/oread`, `~/bin/orun`, or `~/bin/oexec` for any reason (permission rejection, shim unavailable, server down), fall back directly — no Python runner involved: for tasks, write to `owrap/docs/run/tasks/task0.md` then run `opencode run -- --taskf`; for plan execution, run `opencode run -- --execf <plan_path>`. Add `--dangerously-skip-permissions` if needed. Always foreground (no `run_in_background=True`, no owait).

**Fallback modes (--taskf / --execf):** `--taskf [path]` and `--execf [path]` are opencode model instructions only — no `runner.py` handler exists. The model receives the flag and optional path, executes the task/plan, and self-writes output to fixed paths as the **final step before the session ends**: `--taskf` → read task from path if given (else `owrap/docs/run/tasks/task0.md`) → write `owrap/docs/run/output/task0.log` → prepend `owrap/docs/run/log.md` last; `--execf` → read plan from path if given (else `owrap/docs/plan0.md`) → write `owrap/docs/exec/output/exec_output.log` → prepend `owrap/docs/exec/log.md` last. Writing to the log file must be the absolute last action.

## Session Management

Every session begins with `~/bin/owrap start`. This generates a session ID, starts/attaches the opencode server, writes `$HOME/.owrap/session`, and prints orientation. All runtime paths are session-scoped (`log_<id>.md`, `input_<id>.md`).

- `~/bin/owrap start <name>` — start with a specific research project
- `~/bin/owrap start` — start with default_research from config
- `~/bin/owrap stop` — delete session file
- `~/bin/owrap refresh` — re-validate session; re-starts if dead

Read `self.md` at the start of every message pass, without exception.

**After context compaction:** When a turn begins with a conversation summary (i.e. `/compact` was run), run `~/bin/owrap refresh` in bash immediately as the first action before anything else. This re-prints the session orientation and restores the current session ID, file paths, and server URL to context.

## Dispatch Rules

- `~/bin/orun --msg` is always foreground — use `run_in_background=False` in the Bash tool; errors are visible immediately in the tool output
- Parallel `orun --msg`: `orun -i <id> --msg "..."` with `run_in_background=True`; stdout prefixed `[m:<id>]`, log tagged. Pass `-i` first (shim normalises any position). Without `-i`: foreground as normal, no tagging.
- `~/bin/oread` — foreground by default; no tagging. Parallel: `oread -i <id> -f <file> [-d "..."]` with `run_in_background=True`; stdout prefixed `[r:<id>]`, log tagged. Pass `-i` first (shim normalises any position).
    - After dispatch: wait for harness notification — do NOT poll with owrap stat. owrap stat <session_id> is one-shot inspection only. If no notification: investigate ONCE after 1min (oread), 3min (msg/task), 5min (exec). rc=0=ok, rc=2=timeout (rerun -t), rc=143=crashed.
- `~/bin/orun` (file task) and `~/bin/oexec` auto-background and call `owait run`/`owait exec` internally — use `run_in_background=True` in Bash tool and wait for task-notification
- Use `--fg` to force foreground (e.g. for parallel pre-staged `--id N` tasks)
- Parallel dispatch: write task → `~/bin/orun` → wait for `input_<id>.md` to clear → repeat → `owait` per completion
- **Absolute paths rule:** every file reference in a plan step, task file, input submission, or `--msg` argument must be an absolute path. Never use relative paths or bare filenames.

## Self-Modification Rule

When the active plan modifies the opencode helper system itself (`owrap/`, `~/bin/orun`, `~/bin/oexec`, `~/bin/owait`), never dispatch via `~/bin/oexec` — use the fallback directly: `opencode run --dangerously-skip-permissions -- --execf <plan_path>` **in foreground only**. Pass the plan path explicitly so the executor finds it regardless of session state.

## Planner Fallback Rule

If the planner cannot invoke `~/bin/oread`, `~/bin/orun`, or `~/bin/oexec` for any reason (permission rejection, shim unavailable, server down), fall back directly: for tasks, write to `owrap/docs/run/tasks/task0.md` then run `opencode run -- --taskf`; for plan execution, run `opencode run -- --execf <plan_path>`. Add `--dangerously-skip-permissions` if needed. Always foreground.

## Planner File Restrictions

The planner may only edit: `plan_<session_id>.md` (in `owrap/docs/`), `self.md`, `CLAUDE.md`, `AGENTS.md`, and `## TODO` sections in project files. All other file reads must use `~/bin/oread`. Must never run shell commands directly.

## Executor File Restrictions

The executor may edit: code files, `docs/changes/`, `memory.md`, non-TODO sections of project files. May mark TODOs `[x]` but must NOT edit `plan_<session_id>.md` or non-TODO content of `self.md`.

## Planner Sweeps

On every `--planner`, `--check`, or plan-creation run:
1. Move all `[x]` items from `## TODO` into `## DONE`
2. Remove corresponding steps from the active plan's `### Steps` list in `plan_<session_id>.md`

## After Context Compaction

When a turn begins with a conversation summary (i.e. `/compact` was run), run `~/bin/owrap refresh` in bash immediately as the first action before anything else. This re-prints the session orientation and restores the current session ID, file paths, and server URL to context.

## Workflow Rules

- If a request contains `?`, do not apply the change — suggest it and ask for confirmation
- Do not apply unsolicited fixes beyond the current request
- Only change code relevant to the request
- Document every code change in `docs/changes/<codebase>.md`
- Keep documentation entries brief: what changed, which files, why
