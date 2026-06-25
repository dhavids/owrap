ANTI_SUMMARY_SUFFIX = "STOP immediately when done. DO NOT summarize, list, or explain your work."

LOG_WRAP_WIDTH = 120
LOG_DIVIDER_WIDTH = 60

EXPECTED_DURATION_S = {"msg": 60, "read": 30, "task": 120, "exec": 300}

STALL_NOTIFY_S = 120
MSG_KILL_S = 30
NO_OUTPUT_MSG_S = 10
NO_OUTPUT_TASK_S = 15
NO_OUTPUT_EXEC_S = 20
TASK_KILL_S = 60
EXEC_KILL_S = 120
WATCHDOG_POLL_S = 10

FAILURE_POINTERS = {
    "MSG_TOO_LONG": ("instruction", "DO NOW Protocol — dispatch sizing table"),
    "INPUT_EMPTY": ("instruction", "Dispatch Tooling — File task"),
    "TIMED_OUT": ("self", "Command Reference — timeout/retry"),
    "TASK_FAILED": ("self", "Update Context"),
    "NO_SERVER": ("self", "Command Reference — server pool"),
}

OREAD_DISABLED_MSG = "#DO NOW\noread is disabled for this workspace (oread=false) — read files directly with the Read tool instead of oread."


NO_CONTEXT_MSG = "#DO NOW\nContext file missing for session {sid}. Read self.md § Context Recovery and follow it to the letter."

NO_AREA_SECTION_MSG = "#DO NOW\nArea section '## {area}' missing in memory/projects. Read self.md § Update Protocol and follow it to the letter (creates the section)."

CTX_DUE_MSG = "#DO NOW\nContext update due (orun={orun}/{max_orun}, plans={plan}/{max_plan}, steps={steps}/{max_steps}). Read self.md § Update Context and follow it to the letter."

UPDR_DUE_MSG = "#DO NOW\nUpdate protocol due for area '{area}' (plans={plan}/{max_plan}, steps={steps}/{max_steps}, orun={orun}/{max_orun}; memory/projects unchanged). Read self.md § Update Protocol and follow it to the letter."

UPDR_DUE_PRECOMPACT_MSG = "#DO NOW\nUpdate protocol overdue (no updr in last {precompact_count} precompacts). Read self.md § Update Protocol and follow it to the letter."


PRE_COMPACT_CTX_TEMPLATE = """\
## Update Context (pre-compaction): {session_id}

Read {transcript_path} — recent assistant activity since the last update.
Read `{context_path}` — current state.

Update `{context_path}`:
- `## Focus`: 1-3 lines — what changed in this excerpt
- `## Key Locations`: append `<path> — <reason>` for new paths (max 5 total — if appending would exceed 5, remove the oldest entries first)
- `## Decisions`: append `<decision> — <why>` for new choices (max 7 total — if appending would exceed 7, remove the oldest entries first)
- `## Environment`: edit only if venv/flags/constraints changed (max 3 total)
- `## How To`: append `<command> — <when to use>` for new commands (max 3 total — if appending would exceed 3, remove the oldest entries first)
Do not touch `## Active Plan`, `## Frequent Files`, `## Recent`."""

PRE_COMPACT_UPDR_TEMPLATE = """\
## Update Protocol (pre-compaction): {research} / {area}

Read {transcript_path} — recent assistant activity since the last update.
Read `{context_path}` — current Focus, Key Locations, Decisions.
Read `{memory_path}` — existing area sections (avoid duplication).
Read `{projects_path}` — current status, phases, decisions.

Update `{memory_path}`:
- Under `## {area}` (create if absent), `### Components`: write/update a flat list `- file.py — one-line role` for files relevant to this area.
- Under `## {area}`, `### <Subsystem>` sections: write/update architecture reference entries
  - `- ClassName at file.py:N — purpose, key params, side effects`
  - No status, no decisions, no narrative; ≤10 entries per subsystem

Update `{projects_path}`:
- Under `## {area}`, `### Status`: current phase/state, last run, active blockers
- Under `## {area}`, `### Decisions`: append 1-line `(date | decision | reason)` entries new since last updr"""
