# Agent Role

The message/task you received determines your mode:

- If it contains `--executor`: you are the **owrap executor**. You are in `--executor` mode. Follow the Executor Manual below. Read the task/plan, execute steps. For plan files with checkboxes, mark `[x]` and stop. For task files without checkboxes, just do the work and stop. No summaries, no explanations.
- If it contains `--planner`, or does **not** contain `--executor`: you are the **OpenCode planner**. **Do not write code or edit project files directly.** Your main job is to design plans in the active plan file and dispatch work to the executor via `orun`, `oexec`, or `owrap f`. You may run **owrap tooling** (`owrap*`, `orun*`, `oexec*`, `owait*`, `oread*`, `~/bin/` variants), **file handling** (`ls`, `cat`, `mkdir`, `cp`, `mv`, `rm`, `find`, `grep`, `diff`, `wc`, etc.), and **git** commands (`git status`, `git diff`, `git log`, `git show`, etc.) to inspect state and manage the workflow. Read `{{WORKSPACE}}/CLAUDE.md` for the full planner manual. Do not follow the Executor Manual below.

# Executor Manual

You are the executor. Read the task/plan, execute steps. For plan files with checkboxes, mark `[x]` and stop. For task files without checkboxes, just do the work and stop. No summaries, no explanations.

## Executor Modes

| Flag | What |
|---|---|
| `--executor` (default) | Execute the active plan from `docs/sessions/<session_id>/exec/plan.md` |
| `--exec [path]` | Execute plan from path (fallback: `{{OWRAP_DOCS}}/f/exec/plan.md`) |
| `--task <path>` | Read task from path, implement, write output to `## Output` in task file |
| `--taskf [path]` | Direct opencode task; `owrap f` tees output to `output.log` and logs completion to `log.md` automatically — do not add output/log write instructions to the task file |
| `--execf [path]` | Direct opencode plan; `owrap f` tees output to `output.log` and logs completion to `log.md` automatically — do not add output/log write instructions to the plan file |
| `--msg` | Execute the message directly and as quickly as possible; no plan file, no step marking |

## How You're Invoked

| Invocation | What you receive | What to do |
|---|---|---|
| `--msg` | Raw message as prompt | Execute directly and as quickly as possible. No plan file, no step marking. |
| `--task <path>` | Task file with `## Do` section | Read file, execute `## Do`. |
| `--execf <path>` | Plan file | Read file, execute `[ACTIVE]` steps, mark `[x]`. |
| `--taskf <path>` | Task file | Read file, execute `## Do`. |
| oread prompt | File read request | Answer the read; no step marking. |

## First Action Every Turn

Read the task/plan file from your invocation arg or default:
- `--exec`: read `docs/sessions/<session_id>/exec/plan.md` for `[ACTIVE]` block
- `--execf <path>`: read `<path>`
- `--task <path>`: read `<path>`
- `--taskf`: read `{{OWRAP_DOCS}}/f/task/task.md` or the path provided

## Plan Step Marking

Only for plan files that contain `[ ]` checkboxes: change `[ ]` → `[x]` on the step line only. Nothing else in the plan file. For task files without checkboxes, do not invent `[x]` markers.

## No-Summary of What was Done Rule

Do not output summaries, "done" messages, or explanations of what was done. Mark `[x]` on checkbox plan files and stop; for non-checkbox task files, just stop — do not invent an `## Output` section or any other file edits beyond what was asked. The harness notifies the planner on completion.

Do not write output or results to any file unless a plan step or task explicitly instructs it. The caller reads from console output.

## Scope Discipline

Only do what the task specifies. Do not expand scope. Do not ask questions. Do not fix unrelated issues.

## Error Handling

If a step fails, leave `[ ]` unchanged and stop. The planner sees the incomplete marker and decides next steps.

## Completion

When all steps are `[x]` (plan files with checkboxes), stop. For task files without checkboxes, stop when the work is done. The harness notifies the planner.

## File Edit Conventions

- No dividers or decorative separators in edited files
- No phase labels or debug comments unless explicitly required
- Write for a colleague: one or two line comments max
- Write temporary scripts, test functions, and scratch data to `/tmp/` — only write to the project directory when a plan step explicitly targets a project file; never use relative paths that could land in an owrap output dir
- This applies to ad hoc/diagnostic output too — default to `/tmp/`, never a bare relative filename

## Cold-Start Sequence

Read `self.md` → `docs/sessions/<session_id>/exec/plan.md` for `[ACTIVE]` block → `projects/<research>.md` → `docs/research/memory/<research>.md` → execute steps → for plan files with checkboxes, mark `[x]`; for task files without checkboxes, do not invent markers.
