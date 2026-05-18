# AGENTS.md

This file provides guidance when working with code in this repository.

## Agent Modes

**`--executor` (default):** Execute the active plan from `plan_<session_id>.md` and complete TODO items from `projects/<research>.md`. Edit code, `docs/changes/`, `memory.md`, and non-TODO sections of research files. Mark `## TODO` items `[x]` as complete. **Must NOT:** edit `plan_<session_id>.md`, edit non-TODO content of `self.md`, add/remove/reorder TODO items, or rename `## TODO` to `## DONE`.

**`--planner` (override):** Design and maintain the research roadmap. May edit `self.md`, `plan_<session_id>.md` (in `owrap/docs/`), `## TODO` sections of project files, and `CLAUDE.md`. Must NOT edit code files, `docs/changes/`, `memory.md`, or non-TODO sections of research files.

**`--check` (planner review):** Read `[ACTIVE]` plan, read all `[x]` TODO items, verify each changed file matches intent, flag violations, add new TODO items for anything wrong or missing.

**`--agent` (planner + auto-dispatch):** Plan as `--planner`, then dispatch `oexec` (≥ 3 steps) or `orun` (< 3 steps), wait, auto-`--check` via file reads; repeat until all `[ ]` TODOs resolved.

**`--analyser` (think + auto-dispatch):** Think-only mode: write analysis plan + TODOs → dispatch → read output → iterate → delete plan and TODOs when done. Never writes code or runs commands.

**`--task` (hired executor):** Contract-driven execution — reads `owrap/docs/run/tasks/task.md`. Caller writes task file, then runs `orun`. Executor implements, writes output, prepends timestamped line to `log.md`.

**`--taskf [path]` (fallback task executor):** No runner.py involved — opencode executes the task directly. Read the task from `path` if given, otherwise from `owrap/docs/run/tasks/task0.md`. Execute the task fully (same contract format as `--task`). Then as the **absolute last action**: write output to `owrap/docs/run/output/task0.log` and prepend a timestamped title line to `owrap/docs/run/log.md`.

**`--execf [path]` (fallback plan executor):** No runner.py involved — opencode executes the active plan directly. Read the plan from `path` if given, otherwise from `owrap/docs/plan0.md`. Execute the plan steps in order, update `docs/changes/`, mark TODOs `[x]`. Then as the **absolute last action**: write a summary to `owrap/docs/exec/output/exec_output.log` and prepend a timestamped entry to `owrap/docs/exec/log.md`.

**`--start <name>`:** Run `owrap start <name>` in bash to begin a session, then proceed as `--planner`.

## Cold-Start Sequence (Executor)

Read `self.md` → read `plan_<session_id>.md` for `[ACTIVE]` block → read corresponding `projects/<research>.md` → read `memory.md` → execute steps → update `docs/changes/`, `memory.md`, mark TODOs `[x]`.

## Hire-First Rule

Any non-thinking work goes through helpers:
- `oread -f <file>` — cat a file (instant for <500 lines, else summarises)
- `oread -f <dir>` — ls a directory (instant)
- `oread -g <pattern>` — grep recursively in current dir (instant)
- `oread -g <pattern> -f <path>` — grep in specific file or directory (instant)
- `oread -f <file> -s` — summarise via opencode
- `oread -f <file> -d "..."` — targeted query via opencode (55s timeout)
- `orun --msg "..."` — short inline tasks (foreground)
- `orun` — file-based tasks (auto-background + owait)
- `oexec` — multi-step plan execution

**Never** run `cat`, `ls`, `grep`, or direct bash commands — those are denied by permissions.

## Parallel Execution

`orun --msg` — foreground by default, no tagging. Parallel: `orun -i <id> --msg "..."` + `run_in_background=True`; stdout `[m:<id>]`, log tagged. `oread` — same: `oread -i <id> -f <file>` + `run_in_background=True`; stdout `[r:<id>]`. Pass `-i` first in both (shim normalises any position). File tasks always stdout `[t:<task_id>]`. Without `-i`: no tagging, foreground as normal. After dispatching oread (-i) or orun --msg (-i) with run_in_background=True, wait for the task-notification — do not poll. Expect within 60s (oread) or 180s (orun --msg); if none arrives, investigate.

## Workflow Rules

1. **Question marks mean "suggest only":** If a request contains `?`, do not apply — suggest and ask.
2. **Do not apply unsolicited fixes:** Identify issues but do not apply unless explicitly told.
3. **Only change relevant code:** Do not modify unrelated parts.
4. **Document every code change** in `docs/changes/<codebase>.md`.
5. **Comment style:** One or two lines max. No decorative separators, no phase labels.
6. **Absolute paths everywhere:** all file references in plan steps, task files, input submissions, and `--msg` arguments must be absolute paths. Never use relative paths or bare filenames.
