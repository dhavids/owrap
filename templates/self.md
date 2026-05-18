# Research Manager — System Design

## What This Is

A lightweight, file-based research management system for multi-codebase research. Each research topic spans several git repositories and involves distinct sequential phases. This system enables any agent to cold-start, identify the active task, understand which codebases and scripts are involved, and execute correctly without needing the full conversation history.

## Quick Commands

| Command | What it does |
|---|---|
| `owrap start <name>` | Start session with research `<name>`. Maps to `owrap start <name>` in bash. |
| `owrap start` | Start session with default_research from config. |
| `owrap stop` | End session: delete session file. |
| `owrap refresh` | Re-validate session; re-print orientation. |
| `oread -f <file>` | cat file inline (instant <500 lines, else summarises). |
| `oread -f <dir>` | ls directory (instant). |
| `oread -g <pattern> [-f <path>]` | grep pattern in path (or cwd if omitted). Instant. |
| `oread -f <file> -s` | Summarise via opencode. |
| `oread -f <file> -d "..."` | Targeted query via opencode (55s timeout). |
| `orun --msg "..."` | Short inline task. Foreground. |
| `orun` | File task: reads `input_<id>.md`, dispatches `task<N>.md`. Auto-backgrounds + `owait run`. |
| `oexec` | Execute active plan. Auto-backgrounds + `owait exec`. |
| `owait run/exec/read <id>` | Block-wait for completion of a run/exec/read task for session `<id>`. |

## Session Model

Every session calls `owrap start` at boot. This generates a session ID, starts/attaches the opencode server, writes `~/.owrap/sessions/${CLAUDE_CODE_SESSION_ID}.session`, and prints orientation. All runtime paths are session-scoped (`log_<id>.md`, `input_<id>.md`).

## Parallel Dispatch Pattern

`input_<id>.md` is the serialized dispatch queue:
```
write task → orun → wait for input to clear → write next → owait per completion
```

## Hire-First Rule

Any non-thinking work — including file reads — goes through helpers. No exceptions.
- `oread -f <file>` replaces `cat`
- `oread -f <dir>` replaces `ls`
- `oread -g <pattern> [-f <path>]` replaces `grep`
- `orun --msg "..."`, `orun`, `oexec` for all write/execution work

Direct `cat`, `ls`, and `grep` bash commands are denied by permissions.

## File Structure

| File | Role | Location |
|---|---|---|
| `plan_<session_id>.md` | Active research plan | `owrap/docs/plan_<session_id>.md` (session-scoped) |
| `self.md` | System design, conventions | `<research_root>/self.md` or `docs/self.md` fallback |
| `todo.md` | Task list | `docs/todo.md` or `<research_root>/todo.md` (research-dependent) |

## Agent Modes

| Flag | Mode | What to do |
|---|---|---|
| `--planner` | Planner | Design/update plans, add project TODOs |
| `--executor` / `--exec` | Executor | Read `[ACTIVE]` plan → execute → mark TODOs `[x]` |
| `--check` | Planner review | Verify completed TODOs against plan |
| `--agent` | Planner + auto-dispatch | Plan → delegate → verify |
| `--analyser` | Analyser | Think-only: analysis → dispatch → interpret |
| `--task` | Task executor | Contract-driven execution |
| `--setup` | Setup | Configure project via `owrap setup` |
