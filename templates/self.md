# Research System Reference

File-based research manager for multi-codebase MARL research. **Global reference**: session model, file structure, all agent modes, research/memory formats. Read on demand. Planner-specific behaviour, plan format, and context file format live in `CLAUDE.md`.

## Session Model

Every session calls `owrap start` at boot. Resolves session ID via `$SESSION_ID` env or `by_ccsid/$CLAUDE_CODE_SESSION_ID` pointer (mints new if neither). Writes `~/.owrap/sessions/${SESSION_ID}.session` (durable, survives Claude restarts) and `~/.owrap/sessions/by_ccsid/${CLAUDE_CODE_SESSION_ID}` pointer (1-1 window-to-session binding). Also stores `area` (sub-focus within research, e.g. `self-translator`). Exported as `$OWRAP_AREA` env var. Runtime paths are session-scoped under `~/.owrap/docs/sessions/<sid>/`.

## File Structure

| File | Role | Path |
|---|---|---|
| `plan.md` | Active research plan (one `[ACTIVE]` block) | `~/.owrap/docs/sessions/<session_id>/exec/plan.md` |
| `plan.md` | Fallback plan for `--execf` without path | `~/.owrap/docs/f/exec/plan.md` |
| `task.md` | Fallback task for `--taskf` without path | `~/.owrap/docs/f/task/task.md` |
| `output.log` | Full tee of last `owrap f` run | `~/.owrap/docs/f/{exec,task}/output.log` |
| `log.md` | Completion log for `owrap f` | `~/.owrap/docs/f/{exec,task}/log.md` |
| `status.json` | Live state of last `owrap f` run (running/stalled/done/crashed, pids, times, rc) | `~/.owrap/docs/f/{exec,task}/status.json` |
| `input.md` | Serialized dispatch queue (session-scoped) | `~/.owrap/docs/sessions/<id>/run/input.md` |
| `task_<timestamp>.md` | Timestamp-named task files for parallel hires | `~/.owrap/docs/sessions/<id>/run/tasks/task_<timestamp>.md` |
| `output/msg/msg_*.log` | Per-session msg output logs (last 10 retained) | `~/.owrap/docs/sessions/<id>/run/output/msg/msg_*.log` |
| `output/tasks/task_*.log` | Per-session task output logs (last 5 retained) | `~/.owrap/docs/sessions/<id>/run/output/tasks/task_*.log` |
| `context.md` | Session context (auto-managed) | `~/.owrap/docs/sessions/<id>/context.md` |
| `CLAUDE.md` | Claude Code wrapper + planner working manual | `{{WORKSPACE}}/CLAUDE.md` |
| `self.md` | This file — global reference | `{{RESEARCH_ROOT}}/self.md` |
| `AGENTS.md` | Executor working manual | `{{WORKSPACE}}/AGENTS.md` |
| `memory/<research>.md` | Per-project memory | `{{RESEARCH_ROOT}}/memory/<research>.md` |
| `projects/<research>.md` | Per-research overview, phases, environment | `{{RESEARCH_ROOT}}/projects/<research>.md` |
| `{{CHANGES_DIR}}/<codebase>.md` | Per-repo changelogs (executor writes) | `{{CHANGES_DIR}}/<codebase>.md` |

## Project Detail Files (`projects/<research>.md`)

One file per research goal. No YAML frontmatter — all metadata lives in section content.

- `# <research name>` (H1 title).
- `## Overview` — general description of the research/project; `### Structure` (repo layout, CLI/command reference, component tables); `### Environment` (config keys, dependencies, installation, limits); optional `### <Topic>` subsections for cross-area reference material (methodology, log formats, etc.) that applies to the research as a whole.
- One `## <area>` section per area (matches `$OWRAP_AREA` and `memory/<research>.md`'s `## <area>` sections) — `### Status` (current phase/state, last run, active blockers, free text), `### Decisions` (dated table, 1 line each, append-only), and optionally `### Notes` (free-text; user-populated, never overwritten by executor `--updr` dispatches).
- No `## Phases`/`## TODO`/`## DONE` — dated `### Decisions` entries plus `docs/changes/<research>.md` are the historical record going forward.

Steps live in `~/.owrap/docs/sessions/<session_id>/exec/plan.md`, not here.

## Project Memory Structure (`memory/<research>.md`)

Architecture reference cache — fast lookup of where things live. No status, no decisions, no progress narrative. Those belong in `projects/<research>.md`.

Each area occupies one `## <area>` section. Within each area, the FIRST subsection is `### Components` — a flat list of files relevant to that area (`- file.py — one-line role`). Other `### <Subsystem>` sections elaborate ("go deeper") on specific files listed in `### Components`.

```markdown
## <area>

### Components
- `file.py` — one-line role
- `subdir/util.py` — one-line role

### <Subsystem Name>
- `ClassName` at `file.py:N` — brief purpose; key constructor params
- `method(params)` at `file.py:N` — what it does; key side effects or return value
- config key `foo` — where it's read, what it controls
```

Multiple `## <area>` sections can coexist. Executor updates only the target area section.

## Context File Format

- `## Focus` — current phase/goal; update when direction shifts.
- `## Active Plan` — auto-populated from plan file's first 3 open steps. Do not edit manually.
- `## Key Locations` — important paths (one `path — reason` per line).
- `## Decisions` — architectural/design choices.
- `## Environment` — venv path, flags, quirks, constraints.
- `## How To` — useful commands and techniques discovered during work (e.g. grep patterns, log analysis commands, exact invocations that worked well). Append-only; never delete entries.
- `## Frequent Files` / `## Recent` — auto-managed. Do not edit.

## Update Context

You are the planner — you have been running this session and know what changed. Do this now:

1. Run `owrap get context` to read the current context file. Identify what is stale or missing across each section, based on work done since it was last updated:
   - **## Focus** — does it reflect the current phase and state?
   - **## Key Locations** — any new files or paths introduced this session?
   - **## Decisions** — any architectural choices not yet recorded?
   - **## Environment** — any new env facts (flags, configs, tool constraints)?
   - **## How To** — any useful commands or techniques discovered this session? (e.g., exact grep that found something, log analysis command that worked well, a command flag that made a difference)

2. Write a task file to `~/.owrap/docs/sessions/<sid>/run/input.md` in this exact form, then dispatch via `orun`:

```
# Update Context

Update /home/humble/.owrap/docs/sessions/<sid>/context.md — apply the following changes:

## Focus
<full replacement paragraph — current phase, what is active, what is blocked>

## Key Locations — append only new entries (max 5 total — if appending would exceed 5, remove the oldest entries first):
- `absolute/path/to/file.py` — one-line description

## Decisions — append only new entries (max 7 total — if appending would exceed 7, remove the oldest entries first):
| YYYY-MM-DD | <decision> | <reason> |

## How To — append only new entries (max 3 total — if appending would exceed 3, remove the oldest entries first):
- `<command or invocation>` — when to use it / what it does

## Environment — append only new entries (max 3 total — if appending would exceed 3, remove the oldest entries first):
- <fact>: <value>

(omit any section that needs no change)
```

The executor applies exactly what you wrote — it makes no decisions. Provide the full content for ## Focus; for others, append only new entries not already present. Honour the per-section caps stated above by removing oldest entries if the cap would be exceeded.

This must be a **standalone** task with the header **# Update Context**. It must not be lumped or combined with any other tasks.

## Update Protocol

You are the planner — you have been running this session and know what changed. Do this now:

1. Run `{{BIN_DIR}}/owrap get memory` and `{{BIN_DIR}}/owrap get project` to read the current state of both files for the active area.
2. Based on completed plan steps and decisions made since the last `--updr`, identify what is new or changed:
   - **memory** — new files, classes, methods, config flows relevant to this area?
   - **projects status** — has phase/state changed? Any active blockers?
   - **projects decisions** — any architectural choices to record?
3. Write a task file to `~/.owrap/docs/sessions/<sid>/run/input.md` in this exact form, then dispatch via `{{BIN_DIR}}/orun`:

```
# Update Protocol

Update {{RESEARCH_ROOT}}/memory/<research>.md — area ## <area>:

### Components — write/update flat list of files relevant to this area:
- `file.py` — one-line role

### <Subsystem> — write/update architecture reference (omit subsections with no new entries):
- `ClassName at file.py:N` — purpose, key params (≤10 entries per subsystem)

Update {{RESEARCH_ROOT}}/projects/<research>.md — area ## <area>:

### Status
<replacement paragraph — current phase/state, last run, active blockers>

### Decisions — append only new entries:
| YYYY-MM-DD | <decision> | <reason> |

(omit any section that needs no change)
```

The executor applies exactly what you wrote — it makes no decisions.

This must be a **standalone** task with the header **# Update Protocol**. It must not be lumped or combined with any other tasks.

### When to run

Run `--updr` when:
- **Session end** (`--end`): if the run was significant — produced new findings, completed a phase, made an architectural decision, or resolved a blocker. Replicating known results without new insight is not significant.
- **Explicit call**: `--updr [area]` at any time.

### Area

Check your active area with `{{BIN_DIR}}/owrap get area`. If not set and files have multiple `## <area>` sections → set area first via `owrap update-area <research> <area>` before running updr. If files have a single section → infer it. Always specify the area explicitly in the task file — executor updates only that section and never touches others.

### Limits

- `### Components` in memory: flat list only, no nesting.
- Each `### <Subsystem>` block ≤10 entries; use a new subsystem heading if longer.
- `### Decisions` entries in projects: 1 line each; include only entries new since the last `--updr`.

## Context Recovery

If `context.md` does not exist: run `{{BIN_DIR}}/owrap refresh` (calls `create_context()`). If it exists but is missing required sections, write a task to restore them per `## Context File Format` above.

## DO NOW Mechanism

Counters live in `~/.owrap/sessions/<sid>.counters.json` (owrap-managed — never read or edit directly). Resets are mtime-based for context, hash-based for updr. `marked_steps` counts only `[x]` in the current `[ACTIVE]` block.

### Trigger Table

| Condition | `#DO NOW` message text | Action |
|---|---|---|
| Context file missing for session | `#DO NOW\nContext file missing for session {sid}. Read self.md § Context Recovery and follow it to the letter.` | Run `{{BIN_DIR}}/owrap refresh` |
| Area section `## <area>` missing in memory or projects | `#DO NOW\nArea section '## {area}' missing in memory/projects. Read self.md § Update Protocol and follow it to the letter (creates the section).` | Dispatch `--updr` task |
| Context update due | `#DO NOW\nContext update due (orun={orun}/{max_orun}, plans={plan}/{max_plan}, steps={steps}/{max_steps}). Read self.md § Update Context and follow it to the letter.` | Dispatch `--ctx` task |
| Update protocol due | `#DO NOW\nUpdate protocol due for area '{area}' (plans={plan}/{max_plan}, steps={steps}/{max_steps}; memory/projects unchanged). Read self.md § Update Protocol and follow it to the letter.` | Dispatch `--updr` task |

## Fallbacks

If `{{BIN_DIR}}/orun` or `{{BIN_DIR}}/oexec` is unavailable (binary missing, server pool empty, keepalive dead), run fallback dispatches directly via `owrap f <path>` — no server/pool/Manager involved:

- **Task fallback**: write the task to `{{OWRAP_DOCS}}/f/task/task.md` (or any path whose filename contains "task"), then run `~/bin/owrap f <path>`. Mode (`--taskf`) is inferred from the filename.
- **Plan fallback**: write the plan to `{{OWRAP_DOCS}}/f/exec/plan.md` (or any path without "task" in the filename), then run `~/bin/owrap f <path>`. Mode (`--execf`) is inferred from the filename.
- `owrap f <path>` requires the path to exist (errors and exits otherwise), tees the full opencode output to `{{OWRAP_DOCS}}/f/<exec|task>/output.log`, and prepends a completion entry to `{{OWRAP_DOCS}}/f/<exec|task>/log.md` automatically — the plan/task file does NOT need to instruct the executor to write output summaries or log entries.
- `owrap f <path>` writes/updates `{{OWRAP_DOCS}}/f/<exec|task>/status.json` live: `started_at`, `finished_at`, `fallback_pid`, `runner_pid`, `status` (`running`/`stalled`/`done`/`crashed`), `returncode`. It polls `output.log` for new content every 5s; if nothing new for 2 minutes, `status` becomes `"stalled"` (back to `"running"` once output resumes). Poll this file to check on a long-running fallback dispatch without blocking.
- Never use direct tool edits as a substitute — always go through the executor.

## Command Reference

### owrap (session management)
| Flag | What it does |
|---|---|
| `owrap start <name>` | Start/resolve session for workspace `<name>`; exports `$SESSION_ID`, `$OWRAP_AREA` |
| `owrap refresh` | Re-read session state; rebuild context file if missing |
| `owrap sync` | Re-stage templates from config; write sync task for orun to apply |
| `owrap end` | End session; `--updr` runs first if significant |
| `owrap attach` | Bind current window to existing session (1-1 binding) |
| `owrap stop` | Force-remove session binding |
| `owrap setup <path>` | Write per-project config + stage templates |
| `owrap update-area <research> <area>` | Set active area within research |
| `owrap stat <sid>` | Show session stats (tasks, durations, pool state) |
| `owrap keepalive` | Launch/restart keepalive daemon |
| `owrap f <path>` | Fallback: run `--execf`/`--taskf` directly (no server) on `<path>`; mode inferred from filename ("task" in name → `--taskf`, else `--execf`); tees to `f/<mode>/output.log`, logs to `f/<mode>/log.md`; errors if path missing or path doesn't exist |
| `owrap f tstop` | Stop a running/stalled task fallback: SIGTERM the tracked `runner_pid`, mark `f/task/status.json` as `stopped`, log to `f/task/log.md` |
| `owrap f estop` | Stop a running/stalled exec fallback: same as `tstop` but for `f/exec/status.json`/`log.md` |
| `owrap precompact` | PreCompact hook — summarises transcript before compaction |

### oread (file reading, OpenCode)
| Flag | What it does |
|---|---|
| `oread -f <file>` | Cat file inline (≤8000 chars; `-v` forces full) |
| `oread -f <dir>` | List directory |
| `oread -g <pattern> [-f <path>]` | Grep file(s) |
| `oread -f <file> -s [-p <style>]` | Summarise (`--list-styles` for styles) |
| `oread -f <file> -d "..."` | Targeted query (`-t <s>` to extend timeout) |

### nbread (notebook reading)
| Flag | What it does |
|---|---|
| `nbread <nb.ipynb>` | List cells (index, type, first line) |
| `nbread <nb.ipynb> <N>` | Show cell N input |
| `nbread <nb.ipynb> <N> out` | Show cell N input + output |
| `nbread <nb.ipynb> all [out]` | All cells |

### orun (task dispatch, OpenCode)
| Flag | What it does |
|---|---|
| `orun --msg "..."` | Foreground inline task, ≤1024 chars |
| `orun --msg -` | Read task from stdin (multiline) |
| `orun -i <id> --msg "..."` | Parallel task with id `<id>`; `run_in_background=True` |
| `orun --msg "..." --add-context` | Tell the task to read `context.md` for session context before responding |
| `orun --input <path>` | File task from `<path>`; `run_in_background=True` |

**Parallel file task dispatch:** write task A → `orun` → `owait input` → write task B → `orun` → `owait input` (both now running) → `owait run` per completion; max 5 simultaneous.

### oexec (plan execution, OpenCode)
| Flag | What it does |
|---|---|
| `oexec` | Execute `[ACTIVE]` plan; auto-background; harness notifies |
| `oexec --execf <path>` | Execute plan from `<path>` |

### owait (dispatch coordinator)
| Flag | What it does |
|---|---|
| `owait input` | Wait between background dispatches; harness notifies on completion |
| `owait run` | Wait for next task completion; harness notifies |

### Duration defaults
| Setting | Default (s) |
|---|---|
| `expected_duration_msg` | 4 |
| `expected_duration_read` | 4 |
| `expected_duration_task` | 6 |
| `expected_duration_exec` | 30 |
| `msg_kill_s` | 30 |
| `task_kill_s` | 60 |
| `exec_kill_s` | 120 |

### Exit codes
| rc | Meaning |
|---|---|
| `0` | Success |
| `2` | Timeout (rerun with `-t` to extend) |
| `143` | Crashed |

## DONE

<!-- preserved across syncs: do not overwrite existing DONE entries; planner appends -->
