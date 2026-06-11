# Update Protocol

## Trigger Conditions

`--updr` fires automatically on:
- **Phase completion** (Planner Sweep step 4): when `[ACTIVE]` phase is promoted to `[DONE]`
- **Session end** (`--end`): if session had a significant run
- **Explicit call**: `--updr [area]` at any time

## Significance Definition

A run is significant if it:
- Produces new findings (unexpected result, correlation, failure mode)
- Completes a phase or starts a new area
- Establishes an architectural decision
- Resolves or discovers a blocker

Replicating known results or clean runs without new insight are NOT significant.

## Area Handling

- Area is inferred from `$OWRAP_AREA` env (set by `owrap start`/`owrap refresh`/`owrap update-area`).
- If area not set and memory/project files contain multiple `## <area>` sections → do not update; tell the planner to set area first via `owrap update-area <research> <area>`.
- If area not set and files contain a single `## <area>` section → infer and proceed.
- Each area occupies one `## <area>` section in `memory/<r>.md`. Executor updates only that section — never touches other areas.

## File Ownership

| File | What it contains |
|---|---|
| `context_<id>.md` | Current session state: focus, active plan, key locations, recent in-progress decisions |
| `projects/<research>.md` | Research overview: status, phases, decisions, progress, blockers, TODO/DONE history |
| `memory/<research>.md` | Architecture reference cache: file:line, class hierarchy, method signatures, config flows. Indexed by area/subsystem. No status, no decisions, no progress narrative. |

## Read List (before writing the update task)

1. `context_<id>.md` — Focus, Key Locations, Decisions sections
2. `{{OWRAP_DOCS}}/exec/output/exec_output_<session_id>.log` — last executor output
3. `{{RESEARCH_ROOT}}/memory/<research>.md` — existing area sections (avoid duplication)
4. `{{RESEARCH_ROOT}}/projects/<research>.md` — current status, phases, decisions

> Note: `{{RESEARCH_ROOT}}` and `{{OWRAP_DOCS}}` are resolved at staging time.
> `<research>`, `<area>`, `<session_id>`, `<id>` are filled in by the planner at runtime
> using `research` from the session and `area` from `$OWRAP_AREA`.

## Update Task Format

Write a task file (e.g. `input_<id>.md`) that the executor applies verbatim.
Replace `<research>`, `<area>`, `<session_id>` with actual values from the session.

```
## Update Research: <research> / <area>

Update `{{RESEARCH_ROOT}}/memory/<research>.md`:
- Under `## <area>` (create section if absent): write/update architecture reference sections
  - Each subsystem gets a `### <Subsystem>` heading
  - Each entry: `- ClassName at file.py:N — purpose, key params, side effects`
  - No status, no decisions, no narrative — only code map entries

Update `{{RESEARCH_ROOT}}/projects/<research>.md`:
- Update `last_updated` in the YAML header to today's date
- Update `current_phase` in header if phase advanced
- Under `## Status`: update current state, last run, active blockers
- Under `## Decisions`: append new architectural decisions (date | decision | reason)
- Under `## DONE`: append completed phase entries

Write one-line summary to `{{OWRAP_DOCS}}/run/output/task0.log`.
Prepend one-line entry to `{{OWRAP_DOCS}}/run/log.md`.
```
