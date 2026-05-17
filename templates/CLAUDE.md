# CLAUDE.md

This file provides guidance to Claude Code when working with this project.

You are always in **--planner** mode unless a different flag is specified.

## Quick Commands

| Flag | Mode | What to do |
|---|---|---|
| `--start <name>` | Planner | Run `owrap start <name>` in bash, then proceed as --planner |
| *(none)* or `--planner` | Planner | Design/update plans, add project TODOs |
| `--executor` / `--exec` | Executor | Read `[ACTIVE]` plan → execute → mark TODOs `[x]` |
| `--check` | Planner review | Verify completed TODOs against plan |
| `--agent` | Planner + auto-dispatch | Plan → delegate via oread/orun/oexec → verify |
| `--analyser` | Analyser + auto-dispatch | Think-only: analysis plan → dispatch → interpret results |
| `--task` | Task executor | Contract-driven task execution |
| `--taskf` | Fallback | Direct opencode run; model self-writes output to fixed log paths |
| `--execf` | Fallback | Direct opencode run; model self-writes exec output |
| `--setup [research_root]` | Setup | Run `owrap setup [research_root]` in bash (installs shims, sets research_root), then act on the printed FILES and SETTINGS instructions |
| `--refresh` | Refresh | Run `owrap refresh` in bash (re-prints orientation), then check CLAUDE.md, AGENTS.md, self.md against templates — merge missing sections if behind, leave unchanged if already more detailed |

**Hire-first rule:** Delegate any non-thinking work via:
- `oread -f <file> [-s] [-d "..."]` — file reads, verifications (always foreground)
- `orun --msg "..."` — short inline tasks (foreground)
- `orun` — file-based tasks (auto-background + owait)
- `oexec` — multi-step plan execution (auto-background + owait)

Never directly read arbitrary files, run grep, or execute bash commands — use the helpers above.

## Session Management

Every session begins with `owrap start`. This generates a session ID, starts/attaches the opencode server, writes `/tmp/owrap/$PPID.session`, and prints orientation. All runtime paths are session-scoped (`log_<id>.md`, `input_<id>.md`).

- `owrap start <name>` — start with a specific research project
- `owrap start` — start with default_research from config
- `owrap stop` — delete session file
- `owrap refresh` — re-validate session; re-starts if dead

Read `self.md` at the start of every message pass, without exception.

## Dispatch Rules

- `oread` is always foreground — fast (seconds), no benefit from backgrounding
- `orun --msg` is always foreground
- `orun` (file task) and `oexec` auto-background and call `owait run`/`owait exec` internally — use `run_in_background=True` in Bash tool and wait for task-notification
- Use `--fg` to force foreground (e.g. for parallel pre-staged `--id N` tasks)
- Parallel dispatch: write task → `orun` → wait for `input_<id>.md` to clear → repeat → `owait` per completion

## Self-Modification Rule

When the active plan modifies the opencode helper system itself (`owrap/`, `~/bin/orun`, `~/bin/oexec`, `~/bin/owait`), never dispatch via `oexec` — use the fallback directly: `opencode run --dangerously-skip-permissions -- --execf` **in foreground only**.

## Planner Fallback Rule

If the planner cannot invoke `oread`, `orun`, or `oexec` for any reason (permission rejection, shim unavailable, server down), fall back directly: for tasks, write to `docs/research/run/tasks/task0.md` then run `opencode run -- --taskf`; for plan execution, run `opencode run -- --execf`. Add `--dangerously-skip-permissions` if needed. Always foreground.

## Planner File Restrictions

The planner may only edit: `plan_<session_id>.md` (in `owrap/docs/`), `self.md`, `CLAUDE.md`, `AGENTS.md`, and `## TODO` sections in project files. All other file reads must use `oread`. Must never run shell commands directly.

## Executor File Restrictions

The executor may edit: code files, `docs/changes/`, `memory.md`, non-TODO sections of project files. May mark TODOs `[x]` but must NOT edit `plan_<session_id>.md` or non-TODO content of `self.md`.

## Planner Sweeps

On every `--planner`, `--check`, or plan-creation run:
1. Move all `[x]` items from `## TODO` into `## DONE`
2. Remove corresponding steps from the active plan's `### Steps` list in `plan_<session_id>.md`

## After Context Compaction

When a turn begins with a conversation summary (i.e. `/compact` was run), run `owrap refresh` in bash immediately as the first action before anything else. This re-prints the session orientation and restores the current session ID, file paths, and server URL to context.

## Workflow Rules

- If a request contains `?`, do not apply the change — suggest it and ask for confirmation
- Do not apply unsolicited fixes beyond the current request
- Only change code relevant to the request
- Document every code change in `docs/changes/<codebase>.md`
- Keep documentation entries brief: what changed, which files, why
