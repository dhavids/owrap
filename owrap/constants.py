ANTI_SUMMARY_SUFFIX = (
    "STOP immediately when done. DO NOT summarize, list, or explain your "
    "work."
)

LOG_WRAP_WIDTH = 120
LOG_DIVIDER_WIDTH = 60

EXPECTED_DURATION_S = {"msg": 60, "read": 30, "task": 120, "exec": 300, "agent": 120}

STALL_NOTIFY_S = 120
SCRIPT_STALL_MULTIPLIER = 2.0
MSG_KILL_S = 30
NO_OUTPUT_MSG_S = 10
NO_OUTPUT_TASK_S = 15
NO_OUTPUT_EXEC_S = 20
INFRA_FAILURE_MSG_S = 30
INFRA_FAILURE_TASK_S = 40
INFRA_FAILURE_AGENT_S = 45
INFRA_FAILURE_EXEC_S = 45
TASK_KILL_S = 60
EXEC_KILL_S = 120
TASK_HARD_TIMEOUT_S = 600
EXEC_HARD_TIMEOUT_S = 600
WATCHDOG_POLL_S = 10
MSG_MAX_CHARS = 1536
AGENT_KILL_S = 90
NO_OUTPUT_AGENT_S = 20
AGENT_INLINE_MAX_CHARS = 2048
AGENT_TIMEOUT_DEFAULT = 120
AGENT_GRACE_MIN_S = 30
AGENT_GRACE_MAX_S = 60
AGENT_GRACE_LOW_ANCHOR_S = 120
AGENT_GRACE_HIGH_ANCHOR_S = 500
TRASH_RETENTION_DAYS = 30
UNRESPONSIVE_KILL_THRESHOLD = 2

FAILURE_POINTERS = {
    "INPUT_EMPTY": ("instruction", "Runner Tooling — File task"),
    "TIMED_OUT": ("self", "Command Reference — timeout/retry"),
    "NO_SERVER": ("self", "Command Reference — server pool"),
    "INFRA_UNAVAILABLE": (
        "self",
        "Command Reference — infrastructure unavailable",
    ),
}

WATCHDOG_UNRESPONSIVE_MSG = (
    "[watchdog] no response from executor (no output at all) — "
    "{retry_hint}"
)
WATCHDOG_RETRY_HINT_FILE_TASK = (
    "retry as a file task (write input.md, then `orun`)."
)
WATCHDOG_RETRY_HINT_OWRAP_F = "retry via `owrap f`."
WATCHDOG_UNRESPONSIVE_EVICT_SUFFIX = (
    " Server {url} unresponsive too many times, marked for graceful "
    "eviction — will respawn on next dispatch."
)
WATCHDOG_INFRA_FAILURE_MSG = (
    "[watchdog] infra failure — executor did not produce any real "
    "output. Report this to the user and do not retry unless told to "
    "do so."
)
WATCHDOG_KILL_STALL_MSG = (
    "[watchdog] {kind} killed after stalling — dispatch with "
    "--disablewd to prevent the watchdog from killing this task."
)

OREAD_DISABLED_MSG = (
    "#DO NOW\n"
    "oread is disabled for this workspace (oread=false) — read files "
    "directly with the Read tool instead of oread."
)


NO_CONTEXT_MSG = (
    "#DO NOW\n"
    "Context file missing for session {sid}. Read self.md § Context "
    "Recovery and follow it to the letter."
)

NO_AREA_SECTION_MSG = (
    "#DO NOW\n"
    "Area section '## {area}' missing in memory/projects. Read self.md "
    "§ Update Protocol and follow it to the letter (creates the section)."
)


CTX_SCOPED_TASK_TEMPLATE = (
    """\
You are in a directory containing ONLY the file you need — nothing else \
exists for you, no other path is reachable or relevant:
- `transcript.txt` — recent assistant activity since the last update

You have NOT been given the current contents of context.md/memory.md/ \
project.md, and that is deliberate — report ONLY what this excerpt adds, \
never what should stay or go in files you haven't seen. Another process \
merges your additions in and handles caps/eviction; that is not your job.

Write your complete output to `output.md` in this same directory (create \
it). Use exactly this structure — omit an entire top-level `# ` block if \
there is nothing new to say for it:
{blocks}
Do not invent content not supported by `transcript.txt`. Do not explain \
your reasoning in `output.md` — only the structure above."""
)

CTX_CONTEXT_BLOCK = (
    """

# Context
## Focus
<1-3 lines — what changed in this excerpt (this fully replaces the old """
    """Focus text, so it must stand alone)>
## Key Locations
<NEW entries only, one per line — `- path — reason` ONLY for source-code """
    """paths relevant to ongoing/future work (e.g. a function that was """
    """added or changed). A `[Edit]`/`[Write]` marker, or a `[Touched]` """
    """line (a path the planner explicitly reported — may carry its own """
    """` — note`), gives the exact real path — prefer either over """
    """paraphrasing one from prose. `path` must start with the actual file path """
    """(e.g. `dir/file.py`) — never a bare function/class name alone; """
    """append ` — function_name()` after the path if a specific function """
    """matters. Do NOT list a file just because it was mentioned or """
    """`[Read]` in this excerpt — only files actually changed. Never list """
    """transcript.txt, context.md, memory.md, """
    """or project.md themselves. Omit this heading entirely if nothing """
    """new qualifies.>
## Decisions
<NEW entries only, one per line — `- decision — why`. Omit this heading """
    """entirely if no new decision was made in this excerpt.>
## Environment
<only if venv/flags/constraints changed in this excerpt — the full new """
    """text, replacing the old. Otherwise omit this heading entirely.>
## How To
<NEW entries only, one per line — `- command — when to use it`, ONLY for """
    """a command shown verbatim after a `$ ` marker in the excerpt — never """
    """a paraphrase of assistant prose. A `-> ` line right after a `$ ` """
    """command is that command's real output; use it to judge whether the """
    """command actually worked before citing it. Omit this heading """
    """entirely if no real command appears.>"""
)

CTX_PROTOCOL_BLOCK = (
    """

# Memory
## {area}
### Components
<NEW entries only, one per line — `- file.py — one-line role` for files """
    """newly relevant to this area in this excerpt. A `[Edit]`/`[Write]` """
    """marker, or a `[Touched]` line (a path the planner explicitly """
    """reported), gives the exact real path — prefer either over """
    """paraphrasing one from prose. Omit this heading entirely if none """
    """are new.>
### <Subsystem>
<NEW architecture reference entries only, one per line — `- ClassName at """
    """file.py:N — purpose, key params, side effects` — no status, no """
    """decisions, no narrative. Use a real subsystem name as the """
    """heading. Omit this heading entirely if nothing new qualifies.>

# Project
## {area}
### Status
<replacement paragraph — current phase/state, last run, active blockers, """
    """covering only what this excerpt shows (this fully replaces the """
    """old Status text, so it must stand alone)>
### Decisions
<NEW entries only, one per line — `- decision — why` (no date; that is """
    """added when your output is merged in). Omit this heading entirely """
    """if no new decision was made in this excerpt.>"""
)
