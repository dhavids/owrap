# Research System Reference

File-based research manager for multi-codebase MARL research. **Global reference**: session model, file structure, all agent modes, research/memory formats. Read on demand. Planner-specific behaviour, plan format, and context file format live in `CLAUDE.md`.

## Session Model

Every session calls `owrap start` at boot. Resolves session ID via `$SESSION_ID` env, then `by_ccsid/$CLAUDE_CODE_SESSION_ID` pointer, then `by_opencode_run_id/$OPENCODE_RUN_ID` pointer (mints new if none match). Writes `{{OWRAP_HOME}}/sessions/${SESSION_ID}.session` (durable, survives Claude restarts), `{{OWRAP_HOME}}/sessions/by_ccsid/${CLAUDE_CODE_SESSION_ID}` pointer, and `{{OWRAP_HOME}}/sessions/by_opencode_run_id/${OPENCODE_RUN_ID}` pointer (both 1-1 window-to-session bindings). Also stores `area` (sub-focus within research, e.g. `self-translator`). Exported as `$OWRAP_AREA` env var. Runtime paths are session-scoped under `{{OWRAP_HOME}}/docs/sessions/<sid>/`.

## OWRAP_HOME

`{{OWRAP_HOME}}` (rendered above wherever it appears) resolves in this order: `$OWRAP_HOME` env var (if set) > contents of the fixed pointer file `~/.owrap_home` (if it exists) > default `~/.owrap`. Both the Python package (`owrap/utils/paths.py`) and every bash shim (`owrap`, `orun`, `oexec`, `owait`, `oread`) resolve it the same way. To point at a new path, use `owrap update-home <new_path>` (see Command Reference): by default this only updates the pointer file (useful when the target already has valid content, e.g. a synced mount from another machine, or is a fresh path you'll populate via normal use — run `owrap sync` afterward). Pass `--migrate` to actually relocate existing content on the same machine — it backs up first, stops the server pool and daemon, atomically moves the directory, updates the pointer file, and re-syncs the current workspace automatically.

## File Structure

| File | Role | Path |
|---|---|---|
| `plan.md` | Active research plan (one `[ACTIVE]` block) | `{{OWRAP_HOME}}/docs/sessions/<sid>/exec/plan.md` |
| `plan.md` | Fallback plan for `--execf` without path | `{{OWRAP_HOME}}/docs/f/exec/plan.md` |
| `task.md` | Fallback task for `--taskf` without path | `{{OWRAP_HOME}}/docs/f/task/task.md` |
| `output.log` | Full tee of last `owrap f` run | `{{OWRAP_HOME}}/docs/f/{exec,task}/output.log` |
| `log.md` | Completion log for `owrap f` | `{{OWRAP_HOME}}/docs/f/{exec,task}/log.md` |
| `status.json` | Live state of last `owrap f` run (running/stalled/done/crashed, pids, times, rc) | `{{OWRAP_HOME}}/docs/f/{exec,task}/status.json` |
| `input.md` | Serialized dispatch queue (session-scoped) | `{{OWRAP_HOME}}/docs/sessions/<sid>/run/input.md` |
| `task_<timestamp>.md` | Timestamp-named task files for parallel hires | `{{OWRAP_HOME}}/docs/sessions/<sid>/run/tasks/task_<timestamp>.md` |
| `output/msg/msg_*.log` | Per-session msg output logs (last 10 retained) | `{{OWRAP_HOME}}/docs/sessions/<sid>/run/output/msg/msg_*.log` |
| `output/tasks/task_*.log` | Per-session task output logs (last 5 retained) | `{{OWRAP_HOME}}/docs/sessions/<sid>/run/output/tasks/task_*.log` |
| `context.md` | Session context (auto-managed) | `{{OWRAP_HOME}}/docs/sessions/<sid>/context.md` |
| `CLAUDE.md` | Claude Code wrapper + planner working manual | `{{WORKSPACE}}/CLAUDE.md` |
| `self.md` | This file — global reference | `{{RESEARCH_ROOT}}/self.md` |
| `AGENTS.md` | Executor working manual | `{{WORKSPACE}}/AGENTS.md` |
| `memory/<research>.md` | Per-project memory | `{{RESEARCH_ROOT}}/memory/<research>.md` |
| `projects/<research>.md` | Per-research overview, phases, environment | `{{RESEARCH_ROOT}}/projects/<research>.md` |
| `.trash/<sid>/` | Ended/stopped session moved here instead of deleted; swept after 30 days (config `trash_retention_days`) | `{{OWRAP_HOME}}/.trash/<sid>/` |

## Project Detail Files (`projects/<research>.md`)

One file per research goal. No YAML frontmatter — all metadata lives in section content.

- `# <research name>` (H1 title).
- `## Overview` — general description of the research/project; `### Structure` (repo layout, CLI/command reference, component tables); `### Environment` (config keys, dependencies, installation, limits); optional `### <Topic>` subsections for cross-area reference material (methodology, log formats, etc.) that applies to the research as a whole.
- One `## <area>` section per area (matches `$OWRAP_AREA` and `memory/<research>.md`'s `## <area>` sections) — `### Status` (current phase/state, last run, active blockers, free text), `### Decisions` (dated table, 1 line each, append-only), and optionally `### Notes` (free-text; user-populated, never overwritten by executor `--updr` dispatches).
- No `## Phases`/`## TODO`/`## DONE` — dated `### Decisions` entries (capped, newest-first, max 100) are the curated historical record; full change history lives in each codebase's own `git log`/`git diff`.

Steps live in `{{OWRAP_HOME}}/docs/sessions/<sid>/exec/plan.md`, not here.

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

### Child Areas

A child area is created via `owrap start <research> <parent> <child>` or `owrap spawn <child>` (from within an existing `<parent>` session) — the session's area becomes `<parent>-<child>`, and the session file also stores a separate `child` field (just `<child>`, not the combined string). Check `owrap get session` to see whether the current session is a child (`child` row present) and its value — never parse the `area` string for a hyphen to guess this; areas like `data-gen` already contain hyphens without being children. Hyphens in area names are NOT parsed structurally in memory.md/projects.md either — the parent/child relationship in THOSE files is tracked ONLY via the explicit `**Parent area:**` annotation line (a separate, file-level marker from the session's `child` field).

When `--updr` creates a child area's `## <parent>-<child>` section for the first time (in memory.md and/or projects.md), it must include `**Parent area:** <parent>` as the very first line of the section, before `### Components` (memory.md) or `### Status` (projects.md):

```markdown
## <parent>-<child>
**Parent area:** <parent>

### Components
...
```

Collapsing a child area back into its parent is a planner-driven operation, not an `owrap` command — see § Collapse. It requires the `**Parent area:**` annotation to exist; without it, the planner must refuse (not a recognized child area). No nested children — a child area's own section must not itself carry a `**Parent area:**` pointing to another child.

## Context File Format

- `## Focus` — current phase/goal; update when direction shifts.
- `## Active Plan` — auto-populated from plan file's first 3 open steps. Do not edit manually.
- `## Key Locations` — important paths (one `path — reason` per line).
- `## Decisions` — architectural/design choices.
- `## Environment` — venv path, flags, quirks, constraints.
- `## How To` — useful commands and techniques discovered during work (e.g. grep patterns, log analysis commands, exact invocations that worked well). Append-only; never delete entries.
- `## Frequent Files` / `## Recent` — auto-managed. Do not edit.

## Update Context

Run `{{BIN_DIR}}/owrap ctx`. **Fire-and-forget**: it validates fast, queues the actual dispatch on a detached background process, and returns immediately — it does not block waiting for the model. The dispatch runs into a sandboxed directory containing *only* `transcript.txt` (the new assistant activity since the last checkpoint) — the executor never sees `context.md`, `memory.md`, `projects.md`, or any real path; it reports only what's new, never what should stay or be evicted. It writes a structured `output.md`; owrap itself then merges that back into the real `context.md` deterministically — no model judgment involved in capping or eviction. Check `ctx_status` (surfaced automatically in the orientation banner on the next `owrap refresh`/`owrap attach`) to see whether it finished `ok` or `failed`:
- **## Focus** — full replace: 1-3 lines, what changed in this excerpt
- **## Key Locations** — new entries appended (max 5 total — oldest evicted first on overflow); only real source paths relevant to ongoing/future work, never `context.md`/`memory.md`/`projects.md` themselves. On every merge, existing entries whose path no longer exists on disk are pruned first, before the cap is applied.
- **## Decisions** — new entries appended (max 7 total — oldest evicted first on overflow)
- **## Environment** — full replace, only if venv/flags/constraints changed in this excerpt
- **## How To** — new entries appended (max 3 total — oldest evicted first on overflow); only a command shown verbatim (a `$ ` line in the transcript excerpt), never a paraphrase — a `-> ` line right after it is that command's real (truncated) output, usable to judge whether it worked

**If you already know exactly what you changed** and don't want to wait for the transcript to carry it, run `{{BIN_DIR}}/owrap touched <path> [<path> ...] [--note "<one-line note>"]` — the next dispatch (automatic or manual) includes each path as a `[Touched]` entry, treated the same as a real `[Edit]`/`[Write]` marker, and clears the queued list once successfully applied.

## Update Protocol

Run `{{BIN_DIR}}/owrap updr [area]`. Same fire-and-forget behavior and transcript-only sandbox as Update Context, for the given area (default: this session's current area). The executor writes `output.md`; owrap applies it back to the real files the same deterministic way. Need both Context and Protocol updated from the same excerpt? Add `--ctx` (`owrap updr [area] --ctx`, planner shorthand `--uall [area]`) rather than calling `owrap ctx` and `owrap updr` separately — separately dispatches twice against the same unconsumed transcript excerpt (no lock on the checkpoint counter) and costs two model calls instead of one; `--ctx` queues a single background dispatch producing both halves at once, same as the automatic daemon check and `PreCompact` already do:

`{{RESEARCH_ROOT}}/memory/<research>.md` — area `## <area>`:
- `### Components` — new entries appended, deduped, uncapped
- `### <Subsystem>` — a new `### <Subsystem>` heading from the model is appended as its own block (not merged into an existing same-named subsystem — v1 limitation)

`{{RESEARCH_ROOT}}/projects/<research>.md` — area `## <area>`:
- `### Status` — full replace: current phase/state, last run, active blockers
- `### Decisions` — new entries dated and prepended at the top (newest-first; max 150 total — oldest evicted on overflow); the model writes undated `- decision — why` bullets, owrap adds the date

If `## <area>` is a newly-created child area, the executor includes the `**Parent area:**` annotation — see § Child Areas.

### Reliability

Each dispatch tries the configured model, retries it once, then falls back a rung at a time through `context_manager_model` → `runner_model` → `context_fallback_model` (config keys; the last always resolves to a real value — never an arbitrary opencode free-tier pick). Every attempt's `output.md` is validated before being trusted (`## Focus` present if Update Context ran, `### Status` present if Update Protocol ran) — an invalid or missing output doesn't get applied. If every rung fails, nothing is dropped: the transcript checkpoint isn't advanced, so the same unprocessed excerpt is retried on the next trigger instead of being silently lost.

### When to run

- **Automatically, in the background**: the daemon (`{{BIN_DIR}}/owrap daemon`, started by `owrap start`/`owrap refresh`) checks every attached window every `ctx_check_interval_s` (config key, default 300s) for a non-empty transcript diff and dispatches both halves itself if one exists — no manual action needed, and independent of whether the runner (dispatch tooling) is enabled.
- **On PreCompact**: also handled automatically, via the `ctx-hook`/`ctx-worker` pair, right before a compaction would otherwise lose the excerpt.
- **Session end** (`--end`): if the run was significant — produced new findings, completed a phase, made an architectural decision, or resolved a blocker. Replicating known results without new insight is not significant.
- **Explicit call**: `--ctx` / `--updr [area]` at any time, for an immediate update instead of waiting for the next automatic check.

### Area

`owrap updr` defaults to this session's configured area (`{{BIN_DIR}}/owrap get area`) and updates only that `## <area>` section, never touching others. Pass `owrap updr <area>` explicitly to target a different one.

### Limits

- `### Components` in memory: flat list only, no nesting.
- Each `### <Subsystem>` block ≤10 entries; use a new subsystem heading if longer.
- `### Decisions` entries in projects: 1 line each; include only entries new since the last `--updr`; ordered newest-first (new entries prepended at the top, not appended at the bottom); max 150 entries total, oldest removed on overflow.

## Context Recovery

If `context.md` does not exist: run `{{BIN_DIR}}/owrap refresh` (calls `create_context()`). If it exists but is missing required sections, write a task to restore them per `## Context File Format` above.

## Decision Pruning

You are the planner. Heavy, on-demand sweep — never run automatically on `--updr`. Use when a project's `### Decisions` table is cluttered, nearing its cap (150), or you suspect stale entries.

A decision is stale if: **superseded** (a later decision on the same topic reverses it), **dead reference** (cites a `file.py:N`/function/config-key that no longer exists or moved), **duplicate** (re-recorded without new information), or **obsolete** (the code area it describes was fully removed/refactored).

Do this now:

1. Run `{{BIN_DIR}}/owrap get memory` and `{{BIN_DIR}}/owrap get project` for the active area.
2. Extract every cited `file.py:N`/function/config-key from `### Decisions` rows and memory.md's `### Components`/`### <Subsystem>` entries; grep the codebase to confirm each still exists. Anything that doesn't is a **candidate** — flag it, don't remove yet.
3. For each candidate and its immediate neighbors (to catch superseded/duplicate pairs grep alone misses), read enough context to confirm it's genuinely stale, not relocated or renamed.
4. Write a **standalone** task (header `# Decision Pruning`, never lumped with other tasks) to `{{OWRAP_HOME}}/docs/sessions/<sid>/run/input.md` and dispatch via `orun`:

```
# Decision Pruning

Update {{RESEARCH_ROOT}}/memory/<research>.md — area ## <area>:
Remove these entries (dead reference / superseded / duplicate / obsolete — confirmed):
- <entry> — <why>

Update {{RESEARCH_ROOT}}/projects/<research>.md — area ## <area>:
Remove these Decisions rows (dead reference / superseded / duplicate / obsolete — confirmed):
- <row> — <why>
```

The executor removes exactly what you listed — no staleness judgments of its own.

### Safety

`docs/research` is its own git repo — commit before running a prune so removed content stays recoverable via git history. Do not run against an uncommitted/dirty tree.

### When to run

On demand via `--prune [area]` — never automatically, never as part of `--updr`.

## Collapse

You are the planner. This merges a child area's content back into its parent, then removes the child section — used when a child area (see § Child Areas) has run its course and its findings belong under the parent instead.

Do this now:

1. Read the child area's `## <parent>-<child>` section in memory.md and/or projects.md (`owrap get memory`/`owrap get project`, switching area first via `owrap update-area <research> <parent>-<child>` if needed, or read the files directly). Confirm the `**Parent area:** <parent>` annotation is present. If it is missing from BOTH files, STOP — this is not a recognized child area; report the error instead of proceeding.
2. If the annotation is present in only one of the two files, treat that file's parent as authoritative for both, and note the asymmetry in the task you write.
3. Read both the child's and the parent's full content in memory.md and projects.md — everything that needs merging.
4. Decide the merge — don't just concatenate:
   - **Components** (memory.md) — add child files not already listed under the parent; skip exact duplicates.
   - **Subsystems** (memory.md `### <Name>` blocks) — if the parent already has a subsystem with the same name, merge entries into it (dedupe); otherwise add the child's subsystem block as a new one under the parent.
   - **Decisions** (projects.md) — add the child's rows into the parent's table; keep newest-first ordering; respect the 150-row cap (drop oldest on overflow).
   - **Status** (projects.md) — append the child's status as a dated note under the parent's existing Status (`(Collapsed from \`<child>\` on YYYY-MM-DD:)` followed by a condensed summary — don't dump the child's full history verbatim if the parent's Status already covers the same ground).
   - **Notes** (projects.md) — append under the parent's Notes (create the subsection if the parent doesn't have one).
5. Write a task file to `{{OWRAP_HOME}}/docs/sessions/<sid>/run/input.md` in this exact form, then dispatch via `orun`:

```
# Collapse

Update /home/humble/marl/docs/research/memory/<research>.md:
- Merge these entries into ## <parent>'s ### Components (skip if already present):
  - `file.py` — role
- Merge these entries into ## <parent>'s ### <Subsystem> (create the subsystem if absent):
  - <entry>
- Remove the entire ## <parent>-<child> section.

Update /home/humble/marl/docs/research/projects/<research>.md:
- Add these rows to ## <parent>'s ### Decisions (newest-first; cap 150, drop oldest on overflow):
  | YYYY-MM-DD | <decision> | <reason> |
- Append this note to ## <parent>'s ### Status:
  (Collapsed from `<child>` on YYYY-MM-DD:) <condensed summary>
- Append this note to ## <parent>'s ### Notes (create if absent):
  <note text>
- Remove the entire ## <parent>-<child> section.
```

The executor applies exactly what you wrote — it makes no merge decisions of its own; you already decided what's redundant and what's worth keeping in step 4.

This must be a **standalone** task with the header **# Collapse**. It must not be lumped with any other tasks.

6. After the merge task completes:
   a. Read the current session's file (`owrap get session`) to confirm its area matches
      `<parent>-<child>` and find its `parent_session_id` field.
   b. If `parent_session_id` is present: end the child session (`owrap stop`), then
      re-attach the window to the parent (`owrap attach <parent_session_id>`) — this
      restores the parent's own separate context/history as active.
   c. If `parent_session_id` is NOT present (an older child area created before session
      isolation existed, or one created via the legacy in-place `owrap update-area` path):
      fall back to the old behavior — rebind in place via
      `owrap update-area <research> <parent>`.

### Safety

`docs/research` is its own git repo — commit before running a collapse so the removed child section stays recoverable via git history. Do not run against an uncommitted/dirty tree.

### When to run

On demand via `--collapse [child]` (see Planner Modes in `CLAUDE.md`) — never automatically.

## DO NOW Mechanism

Counters live in `{{OWRAP_HOME}}/sessions/<sid>.counters.json` (owrap-managed — never read or edit directly), used for the recovery checks below. The context manager's own transcript-offset tracking lives separately per attached window, in `<sid>.<ccsid>.counters.json`.

### Trigger Table

| Condition | `#DO NOW` message text | Action |
|---|---|---|
| Context file missing for session | `#DO NOW\nContext file missing for session {sid}. Read self.md § Context Recovery and follow it to the letter.` | Run `{{BIN_DIR}}/owrap refresh` |
| Area section `## <area>` missing in memory or projects | `#DO NOW\nArea section '## {area}' missing in memory/projects. Read self.md § Update Protocol and follow it to the letter (creates the section).` | Dispatch `--updr` task |

## Fallbacks

If `{{BIN_DIR}}/orun` or `{{BIN_DIR}}/oexec` is unavailable (binary missing, server pool empty, daemon dead), run fallback dispatches directly via `owrap f <path>` — no server/pool/Manager involved:

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
| `owrap update-area <research> <area> [child]` | Set active research AND area on the current session (both fields updated independently — pass the same area to change only research, or vice versa). `[child]` sets the session's `child` field when this area is a child area; omit it to clear/unset the field (e.g. when rebinding back to a parent after a collapse) |
| `owrap spawn <child>` | Rebind current session to a child area `<parent>-<child>`, where `<parent>` is the session's current area |
| `owrap update-home <path> [--dry-run]` | Point `OWRAP_HOME` at `<path>` — lightweight: validates target, updates `~/.owrap_home` pointer file only. Run `owrap sync` afterward. |
| `owrap update-home <path> --migrate [--dry-run]` | Relocate `OWRAP_HOME`: backs up to `~/.owrap_backups/`, stops server pool + daemon, atomically moves the directory, updates the pointer file, re-syncs current workspace |
| `owrap stat <sid>` | Show session stats (tasks, durations, pool state) |
| `owrap daemon` | Launch/restart the owrap daemon |
| `owrap get <what>` | Print a session resource: `plan`, `input`, `context`, `session`, `memory`, `project`, `area`, `research`, `config`, `home`, `agents`, `output` |
| `owrap get output <msg\|task\|agent\|exec> [--id <id>] [--head N] [--tail N]` | Print the resolved output log path + head/tail preview for the most recent (or a specific `--id`) msg/task/agent dispatch; `exec`/`task` fall back to the single `owrap f` output log when no session is active |
| `owrap f <path>` | Fallback: run `--execf`/`--taskf` directly (no server) on `<path>`; mode inferred from filename ("task" in name → `--taskf`, else `--execf`); tees to `f/<mode>/output.log`, logs to `f/<mode>/log.md`; errors if path missing or path doesn't exist |
| `owrap f tstop` | Stop a running/stalled task fallback: SIGTERM the tracked `runner_pid`, mark `f/task/status.json` as `stopped`, log to `f/task/log.md` |
| `owrap f estop` | Stop a running/stalled exec fallback: same as `tstop` but for `f/exec/status.json`/`log.md` |
| `owrap restore trash <sid>` | Restore a session previously moved to `.trash` by `owrap end`/`owrap stop`; run `owrap attach <sid>` afterward to bind a window to it |
| `owrap backup <research>` | Snapshot `memory.md`/`projects.md`/`todo.md` for `<research>` into `{{OWRAP_HOME}}/backups/<research>/<timestamp>/` — a manual safety net, not automatic |
| `owrap retrieve <research> [timestamp\|latest]` | Restore those files from a backup snapshot; omit `[timestamp]` to list available ones first. `timestamp` may be an unambiguous prefix, resolved the same way as `owrap set model`'s query matching (AMBIGUOUS error if it matches more than one). Distinct from `owrap restore trash`, which restores a trashed *session*, not a file backup |
| `owrap delete backup <research> [latest\|all\|timestamp]` | Delete a backup snapshot — `latest` (default) removes only the newest, `all` removes every snapshot for `<research>`, or name a timestamp prefix (same ambiguity resolution as `retrieve`). The supported way to clean these up instead of `rm -rf`ing them directly |
| `owrap cleanup trash` | Permanently delete `.trash` entries older than `trash_retention_days` (default 30); also runs automatically via `_housekeeping` on `owrap start`/`refresh` |
| `owrap ctx-hook` | PreCompact hook — spawns the context-manager worker before compaction |

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
| `orun --msg "..."` | Foreground inline task, ≤1536 chars |
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

### oagent (subagent dispatch, OpenCode)
| Flag | What it does |
|---|---|
| `oagent <<'OAGENT_PAYLOAD_END' ... OAGENT_PAYLOAD_END` | Pipe the payload in via a quoted-delimiter heredoc; default timeout 120s |
| `oagent -t <seconds> <<'OAGENT_PAYLOAD_END' ... OAGENT_PAYLOAD_END` | Set the time budget |
| `oagent -i <id> <<'OAGENT_PAYLOAD_END' ... OAGENT_PAYLOAD_END` | Parallel dispatch with id `<id>`; `run_in_background=True` |
| `oagent --clear <<'OAGENT_PAYLOAD_END' ... OAGENT_PAYLOAD_END` | Clear prior agent output before dispatching |
| `owrap get agents` | Read back all dispatched agent summaries |

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
| `1` | Infra failure — the model responded (banner logged) but produced no real work. Recorded as `failure_kind: infra_failure`. Report to the user; do not retry unless told to. |
| `2` | Timeout (rerun with `-t` to extend). Recorded as `failure_kind: timeout`. |
| `3` | Crashed — genuine process failure unrelated to our categories. Recorded as `failure_kind: crashed`. |
| `4` | Unresponsive — no output at all, not even the model banner. Recorded as `failure_kind: unresponsive`. A connectivity/availability problem — retry-worthy (msg → file task, task/exec → `owrap f`). |
| `-15` | Killed by watchdog after real output appeared, then stalled (genuine stall — not infra; Python's raw SIGTERM-kill value). Recorded as `failure_kind: stalled`. |
| `143` | Stale/orphaned sentinel reaped (process died without any cleanup). Recorded as `failure_kind: reaped`. |

Categories with `failure_kind` are tracked explicitly rather than inferred from rc.

On any non-zero exit (`status: FAILED`), the previously-dispatched `input.md` content is not safe to redispatch unchanged — rewrite the task file (get its path via `owrap get input`) with corrected content before redispatching via `orun`.

## DONE

<!-- preserved across syncs: do not overwrite existing DONE entries; planner appends -->
