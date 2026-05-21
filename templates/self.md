# Research Manager — System Design

## What This Is

A lightweight, file-based research management system for multi-codebase research. Each research topic spans several git repositories and involves distinct sequential phases. This system enables any agent to cold-start, identify the active task, understand which codebases and scripts are involved, and execute correctly without needing the full conversation history.

## Quick Commands

| Command | What it does |
|---|---|
| `owrap start <name>` | Start session for research `<name>`. |
| `owrap start` | Start session with default_research from config. |
| `owrap stop` | Kill opencode server and clear all session files. |
| `owrap cleanup` | Remove stale sessions (dead server or URL mismatch). Safe with live server. |
| `owrap refresh` | Re-validate session; re-print orientation. |
| `owrap stat` | Show all active sessions, server liveness, and age. |
| `owrap finish <target>` | Kill running job (exec/task1/msg1/…). Sends SIGTERM to its PID. Use when a job hangs. |
| `oread -f <file>` | cat inline if ≤8000 chars, else summarises. Add `-v` to bypass limit and print full file. Always foreground — chain multiple oreads with `&&`. |
| `oread -f <dir>` | ls directory (instant). Replaces `ls`. |
| `oread -g <pattern> [-f <path>]` | grep pattern in path or cwd (instant). Replaces `grep`. |
| `oread -f <file> -s [-p <style>]` | Summarise via opencode; auto-detects style by file extension; timeout scales with file size (45–180s). `-p` to override. `oread --list-styles` to see all options. |
| `oread -f <file> -d "..."` | Targeted query via opencode (55s timeout; `-t <s>` to extend). |
| `orun --msg "..."` | Single line, ≤1024 chars. Foreground, no tagging. Parallel: `orun -i <id> --msg "..."` + `run_in_background=True`; stdout `[m:<id>]`, log tagged. `-i` first. Parallel limit: max 3 — write input + orun for 4–6, plan for 7+. |
| Parallel notify | Use `run_in_background=True` on each Bash tool call — NOT `&`. After dispatching with `run_in_background=True`, make no further tool calls — not `true` keepalives, not `owrap stat`, nothing. The harness delivers the notification automatically when the task exits. Only if no notification arrives after the threshold (1min oread, 3min msg/task, 5min exec), investigate once with `owrap stat <session_id>`. rc=0=ok, rc=2=timeout (rerun -t), rc=143=crashed. **Multiple oreads:** always chain with `&&` in one foreground Bash call — never background. |
| `orun` | File task: reads `input_<id>.md`, dispatches `task<N>.md`. Auto-backgrounds + `owait run`. |
| `oexec` | Execute active plan. Auto-backgrounds + `owait exec`. |

## Session Model

Every session calls `owrap start` at boot. This generates a session ID, starts/attaches the opencode server, writes `~/.owrap/sessions/${CLAUDE_CODE_SESSION_ID}.session`, and prints orientation. All runtime paths are session-scoped (`log_<id>.md`, `input_<id>.md`). Multiple concurrent windows each get their own session automatically.

## Parallel Dispatch Pattern

`input_<id>.md` is the serialized dispatch queue:
```
write task → orun → owait input → write next → owait run per completion
```
`owait input` blocks until the input file is cleared (task picked up by runner), then prints `input clear`. Use it between orun calls when staging parallel file tasks.

## Hire-First Rule

Any non-thinking work — including file reads — goes through helpers. No exceptions.
- `oread -f <file>` replaces `cat`
- `oread -f <dir>` replaces `ls`
- `oread -g <pattern> [-f <path>]` replaces `grep`
- `orun --msg "..."`, `orun`, `oexec` for all write/execution work

Direct `cat`, `ls`, `grep`, and Read are allowed — oread recommended for large files and directories.

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
| `--executor` / `--exec` | Executor | Read `[ACTIVE]` plan → execute → mark completed steps `[x]` in plan file |
| `--check` | Planner review | Chain all file reads: `oread -f a && oread -f b && ...` — one combined output. Flag violations as `[ ]` TODOs. No code changes. |
| `--agent` | Planner + auto-dispatch | Plan → delegate → verify |
| `--analyser` | Analyser | Think-only: analysis → dispatch → interpret |
| `--task` | Task executor | Contract-driven execution |
| `--setup` | Setup | Configure project via `owrap setup` |
