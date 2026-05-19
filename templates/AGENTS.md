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

**Completion notifications (planner rule):** All helpers run in foreground (blocking). For parallel execution, issue multiple concurrent tool calls — each runs its own foreground helper simultaneously. orun (file task) and oexec auto-background and call `owait run`/`owait exec` internally — call them with `run_in_background=True` in the Bash tool and wait for the task-notification. Use `--fg` to force foreground. `orun --msg` — foreground by default. Parallel: `orun -i <id> --msg "..."` + `run_in_background=True` on the Bash tool; stdout `[m:<id>]`. `oread` — same: `oread -i <id> -f <file>` + `run_in_background=True`; stdout `[r:<id>]`. Pass `-i` first. Without `-i`: foreground, no tagging. File tasks always `[t:<task_id>]`. After dispatch: wait for harness notification — do NOT poll with owrap stat. owrap stat <session_id> is one-shot inspection only, not sync. If no notification: investigate ONCE after 1min (oread), 3min (msg/task), 5min (exec). rc=0=ok, rc=2=timeout (rerun -t), rc=143=crashed.

## Hire-First Rule

Any non-thinking work goes through helpers:
- `oread -f <file>` — cat a file (instant for <500 lines, else summarises)
- `oread -f <dir>` — ls a directory (instant)
- `oread -g <pattern>` — grep recursively in current dir (instant)
- `oread -g <pattern> -f <path>` — grep in specific file or directory (instant)
- `oread -f <file> -s` — summarise via opencode
- `oread -f <file> -d "..."` — targeted query via opencode (55s timeout; `-t <s>` to extend)
- **Multiple oreads:** chain with `&&` in ONE foreground Bash call — one combined output, no notifications, no early-read risk. Parallel background (`run_in_background=True` + `-i <id>`) only when true concurrency matters; wait for ALL notifications before reading any output.
- `orun --msg "..."` — short inline tasks (foreground)
- `orun` — file-based tasks (auto-background + owait)
- `oexec` — multi-step plan execution

All planner tool use is blocked — no exceptions, no prompting. The Read, Edit, Write, and Bash tools will be denied by permissions. Do not attempt them, not even inside compound commands (e.g. `ls && oread ...` — the `ls` part is still a denied command). Do not ask the user for permission to use any tool. owrap is the only interface: `oread` for reads, `orun` for writes/edits/commands, `oexec` for plan execution. If owrap is unavailable: `--taskf`/`--execf` fallbacks only. Never direct tools. Never user prompting.

## Parallel Execution

`orun --msg` — foreground by default. Parallel: `orun -i <id> --msg "..."` + `run_in_background=True` on the Bash tool; stdout `[m:<id>]`. `oread` — same: `oread -i <id> -f <file>` + `run_in_background=True`; stdout `[r:<id>]`. Pass `-i` first. File tasks always stdout `[t:<task_id>]`. Without `-i`: foreground, no tagging. After dispatch: wait for harness notification — do NOT poll with owrap stat. owrap stat <session_id> is one-shot inspection only, not sync. If no notification: investigate ONCE after 1min (oread), 3min (msg/task), 5min (exec). rc=0=ok, rc=2=timeout (rerun -t), rc=143=crashed.

## Workflow Rules

1. **Question marks mean "suggest only":** If a request contains a `?`, do not apply the change — suggest it and ask the user for confirmation.
2. **Do not apply unsolicited fixes:** If you identify an issue or improvement beyond the current request, suggest it but do not apply it unless the user explicitly says to.
3. **Only change code relevant to the request:** Do not modify unrelated parts of the code. Mention unrelated issues separately if found.
4. **Document every applied change in `docs/changes/`:** Each codebase has a corresponding file (e.g., `turtlebot_il.md`, `translator.md`, `mappo.md`, `mappo_gail.md`, `argos_il.md`). Create it if missing. Each file has a **TODO** section at the top and a **CHANGES** section below.
5. **Change entry format:** Heading: `### YYYY-MM-DD HH:MM — <title>`. Add an anchor above: `<a id="YYYY-MM-DD-HH-MM"></a>`. Sort descending (most recent first). Run `date` to get the current timestamp. Changes to the same file within 1 hour must be combined into a single entry.
6. **Check TODOs before applying changes:** Before applying any change, check the relevant `docs/changes/` file for unresolved TODO items and inform the user.
7. **When a TODO is fully resolved, move it to CHANGES** with a full entry. If partial, keep it in TODO with a note.
8. **Cross-codebase changes:** If a change spans multiple codebases, split into one entry per `docs/changes/` file with cross-references: `**See also:** [file.md YYYY-MM-DD HH:MM](path/to/file.md#YYYY-MM-DD-HH-MM)`.
9. **Debug code markers:** Temporary debug changes use `# DEBUG start` / `# DEBUG end` block indicators and do not need documentation.
10. **Keep documentation entries brief:** State what changed, which files, and why. No usage examples or extended rationale.
11. **Update research memory after significant changes:** After updating the changelog, also update `docs/research/memory.md` if there are new research findings, architectural decisions, or known issues. Do not create it if it does not exist.
12. **Comment style:** Comments are for the user — write them as if explaining to a colleague. One or two lines max. Use inline comments only when the code block itself doesn't make the intent clear. No decorative separators (`---`, `===`), no phase labels, no disjointed block comments. No dashes (`-`) in comments unless explicitly needed. If a block comment already explains what's happening, don't add redundant inline comments.
13. **Plan step status is planner-only:** The Executor must NOT mark plan steps as done (e.g., strikethrough `~~`) in `plan.md`. Only the Planner (`--planner` mode) modifies plan step status. The Executor marks TODOs `[x]` in `projects/<research>.md` files only.
14. **Absolute paths everywhere:** all file references in plan steps, task files, input submissions, and `--msg` arguments must be absolute paths. Never use relative paths or bare filenames.
