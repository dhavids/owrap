# AGENTS.md

This file provides guidance when working with code in this repository.

## Agent Modes

**`--executor` (default):** Execute the active plan from `plan_<session_id>.md` and complete TODO items from `projects/<research>.md`. Edit code, `docs/changes/`, `memory.md`, and non-TODO sections of research files. Mark `## TODO` items `[x]` as complete. **Must NOT:** edit `plan_<session_id>.md`, edit non-TODO content of `self.md`, add/remove/reorder TODO items, or rename `## TODO` to `## DONE`.

**`--planner` (override):** Design and maintain the research roadmap. May edit `self.md`, `plan_<session_id>.md` (in `owrap/docs/`), `## TODO` sections of project files, and `CLAUDE.md`. Must NOT edit code files, `docs/changes/`, `memory.md`, or non-TODO sections of research files.

**`--check` (planner review):** Read `[ACTIVE]` plan, read all `[x]` TODO items, verify each changed file matches intent, flag violations, add new TODO items for anything wrong or missing.

**`--agent` (planner + auto-dispatch):** Plan as `--planner`, then dispatch `oexec` (≥ 3 steps) or `orun` (< 3 steps), wait, auto-`--check` via file reads; repeat until all `[ ]` TODOs resolved.

**`--analyser` (think + auto-dispatch):** Think-only mode: write analysis plan + TODOs → dispatch → read output → iterate → delete plan and TODOs when done. Never writes code or runs commands.

**`--task` (hired executor):** Contract-driven execution — reads `docs/research/run/tasks/task.md`. Caller writes task file, then runs `orun`. Executor implements, writes output, prepends timestamped line to `log.md`.

**`--start <name>`:** Run `owrap start <name>` in bash to begin a session, then proceed as `--planner`.

## Cold-Start Sequence (Executor)

Read `self.md` → read `plan_<session_id>.md` for `[ACTIVE]` block → read corresponding `projects/<research>.md` → read `memory.md` → execute steps → update `docs/changes/`, `memory.md`, mark TODOs `[x]`.

## Hire-First Rule

Any non-thinking work goes through helpers:
- `oread -f <file>` — file reads, verifications
- `orun --msg "..."` — short inline tasks
- `orun` — file-based tasks
- `oexec` — multi-step plan execution

Never directly read arbitrary files, run grep, or execute bash.

## Parallel Execution

`orun` (file task) and `oexec` auto-background and call `owait run`/`owait exec` internally. Use `--fg` to force foreground. `orun --msg` is always foreground. `oread` is always foreground.

## Workflow Rules

1. **Question marks mean "suggest only":** If a request contains `?`, do not apply — suggest and ask.
2. **Do not apply unsolicited fixes:** Identify issues but do not apply unless explicitly told.
3. **Only change relevant code:** Do not modify unrelated parts.
4. **Document every code change** in `docs/changes/<codebase>.md`.
5. **Comment style:** One or two lines max. No decorative separators, no phase labels.
