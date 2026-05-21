# AGENTS.md

This file provides guidance when working with code in this repository.

## Agent Modes

**`--executor` (default):** Execute the active plan from `plan_<session_id>.md`. Edit code, `docs/changes/`, and `memory.md`. Mark completed plan steps `[x]` — **ONLY** changing `[ ]` to `[x]` on the step line; no other text may be added to the plan file. **Must NOT:** edit non-TODO content of `self.md`, add/remove/reorder plan steps, or make any other change to `plan_<session_id>.md`.

**`--planner` (override):** Design and maintain the research roadmap. May edit `self.md`, `plan_<session_id>.md` (in `owrap/docs/`), `## TODO` sections of project files, and `CLAUDE.md`. Must NOT edit code files, `docs/changes/`, `memory.md`, or non-TODO sections of research files.

**`--check` (planner review):** Read `[ACTIVE]` plan and all `[x]` TODO items; verify each changed file by chaining all `oread` calls in one Bash call: `oread -f file1 && oread -f file2 && ...` — one combined output, all checks at once. Flag violations, add new `[ ]` TODO items for anything wrong or missing.

**`--agent` (planner + auto-dispatch):** Plan as `--planner`, then dispatch `oexec` (≥ 3 steps) or `orun` (< 3 steps), wait, auto-`--check` via file reads; repeat until all `[ ]` TODOs resolved.

**`--analyser` (think + auto-dispatch):** Think-only mode: write analysis plan + TODOs → dispatch → read output → iterate → delete plan and TODOs when done. Never writes code or runs commands.

**`--task` (hired executor):** Contract-driven execution — reads `owrap/docs/run/tasks/task.md`. Caller writes task file, then runs `orun`. Executor implements, writes output, prepends timestamped line to `log.md`.

**`--taskf [path]` (fallback task executor):** No runner.py involved — opencode executes the task directly. Read the task from `path` if given, otherwise from `owrap/docs/run/tasks/task0.md`. Execute the task fully (same contract format as `--task`). Then as the **absolute last action**: write output to `owrap/docs/run/output/task0.log` and prepend a timestamped title line to `owrap/docs/run/log.md`.

**`--execf [path]` (fallback plan executor):** No runner.py involved — opencode executes the active plan directly. Read the plan from `path` if given, otherwise from `owrap/docs/plan0.md`. Execute the plan steps in order, update `docs/changes/`, mark completed steps `[x]` in the plan file. Then as the **absolute last action**: write a summary to `owrap/docs/exec/output/exec_output.log` and prepend a timestamped entry to `owrap/docs/exec/log.md`.

**`--start <name>`:** Run `owrap start <name>` in bash to begin a session, then proceed as `--planner`.

**`--setup [project_root] [research_folder]`:** Run `owrap setup [project_root] [research_folder]` in bash, then act on the printed FILES and SETTINGS instructions.

**`--refresh`:** Run `owrap refresh` in bash to re-print orientation and restore session context.

## Cold-Start Sequence (Executor)

Read `self.md` → read `plan_<session_id>.md` for `[ACTIVE]` block → read corresponding `projects/<research>.md` → read `memory/<research>.md` → execute steps → update `docs/changes/`, `memory/<research>.md`, mark completed steps `[x]` in plan file.

**Completion notifications (planner rule):** All helpers run in foreground (blocking). For parallel execution, issue multiple concurrent tool calls — each runs its own foreground helper simultaneously. orun (file task) and oexec auto-background and call `owait run`/`owait exec` internally — call them with `run_in_background=True` in the Bash tool and wait for the task-notification. Use `--fg` to force foreground. `orun --msg` — foreground by default. Parallel: `orun -i <id> --msg "..."` + `run_in_background=True` on the Bash tool; stdout `[m:<id>]`. `oread` — always foreground, no tagging, no background dispatch. File tasks always `[t:<task_id>]`. After dispatching with `run_in_background=True`, make no further tool calls — not `true` keepalives, not `owrap stat`, nothing. The harness delivers the notification automatically when the task exits. Only if no notification arrives after the threshold (1min oread, 3min msg/task, 5min exec), investigate once with `owrap stat <session_id>`. rc=0=ok, rc=2=timeout (rerun -t), rc=143=crashed. Parallel `--msg` limit: max 3 simultaneous — LLM contention causes timeouts above this. For 4–6 operations: write to the input file and call `orun`; for 7+ steps: use a plan (`oexec`).

## Hire-First Rule

Any non-thinking work goes through helpers:
- `oread -f <file>` — cat a file (instant for ≤8000 chars, else summarises)
- `oread -f <file> -v` — full cat bypassing the 8000-char limit (instant)
- `oread -f <dir>` — ls a directory (instant)
- `oread -g <pattern>` — grep recursively in current dir (instant)
- `oread -g <pattern> -f <path>` — grep in specific file or directory (instant)
- `oread -f <file> -s [-p <style>]` — summarise via opencode; auto-detects style by extension; timeout scales with file size (45–180s); `-p` to override; `oread --list-styles` for all styles
- `oread -f <file> -d "..."` — targeted query via opencode (55s timeout; `-t <s>` to extend)
- **Multiple oreads:** always chain with `&&` in ONE foreground Bash call — never use `-i` or `run_in_background=True` for oread.
- `orun --msg "..."` — short inline tasks (foreground, single line, ≤1024 chars)
- `orun` — file-based tasks (auto-background + owait)
- `oexec` — multi-step plan execution

All planner tool use is blocked — no exceptions, no prompting. The Edit, Write, and Bash tools will be denied by permissions. Read is permitted. Do not attempt Edit/Write/Bash directly, not even inside compound commands (e.g. `ls && oread ...` — the `ls` is still a denied Bash call). Do not ask the user for permission to use any tool. oread is the primary interface: `oread` for reads (direct Read also allowed), `orun` for writes/edits/commands, `oexec` for plan execution. If owrap is unavailable: `--taskf`/`--execf` fallbacks only. Never direct Edit/Write/Bash. Never user prompting.

## Parallel Execution

`orun --msg` — foreground by default. Parallel: `orun -i <id> --msg "..."` + `run_in_background=True` on the Bash tool; stdout `[m:<id>]`. `oread` — always foreground, no background dispatch. File tasks always stdout `[t:<task_id>]`. Without `-i`: foreground, no tagging. After dispatching with `run_in_background=True`, make no further tool calls — not `true` keepalives, not `owrap stat`, nothing. The harness delivers the notification automatically when the task exits. Only if no notification arrives after the threshold (1min oread, 3min msg/task, 5min exec), investigate once with `owrap stat <session_id>`. rc=0=ok, rc=2=timeout (rerun -t), rc=143=crashed. To cancel a running job: `owrap finish <target>` (exec/task1/msg1/…) — sends SIGTERM. Parallel `--msg` limit: max 3 simultaneous — LLM contention causes timeouts above this. For 4–6 operations: write to the input file and call `orun`; for 7+ steps: use a plan (`oexec`).

**Parallel file task staging:** write task → `orun` (run_in_background=True) → `owait input` (blocks until input clear, prints `input clear`) → write next task → `orun`. Call `owait run` once per expected completion. Never use a manual `until` loop to wait for input — use `owait input` instead.

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
11. **Update research memory after significant changes:** After updating the changelog, also update `docs/research/memory/<research>.md` if there are new research findings, architectural decisions, or known issues. Do not create it if it does not exist.
12. **Comment style:** Comments are for the user — write them as if explaining to a colleague. One or two lines max. Use inline comments only when the code block itself doesn't make the intent clear. No decorative separators (`---`, `===`), no phase labels, no disjointed block comments. No dashes (`-`) in comments unless explicitly needed. If a block comment already explains what's happening, don't add redundant inline comments.
13. **Plan step marking — minimal only:** The Executor marks completed plan steps by changing `[ ]` to `[x]` on the step line in `plan_<session_id>.md` — **that is the only permitted change to the plan file**. No other text may be added: no comments, no strikethrough, no status notes. Multiple executors can work the same plan without conflict because each only appends `[x]` to its own step line.
14. **Absolute paths everywhere:** all file references in plan steps, task files, input submissions, and `--msg` arguments must be absolute paths. Never use relative paths or bare filenames.
