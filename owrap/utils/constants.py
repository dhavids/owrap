ANTI_SUMMARY_SUFFIX = (
    "STOP immediately when done. DO NOT summarize, list, or explain your "
    "work."
)

LOG_WRAP_WIDTH = 120
LOG_DIVIDER_WIDTH = 60

EXPECTED_DURATION_S = {"msg": 60, "read": 30, "task": 120, "exec": 300, "agent": 120}

STALL_NOTIFY_S = 120
CTX_IDLE_TIMEOUT_S = 60
SCRIPT_STALL_MULTIPLIER = 2.0

DECISION_NOTICE_THRESHOLD = 35
DECISION_ESCALATE_THRESHOLD = 40
DECISION_PRUNE_TARGET_MIN = 5
DECISION_PRUNE_TARGET_MAX = 10
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
RECENT_TASK_RETENTION_S = 120
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
    "Context file missing for session {sid}. Run `owrap get self`, then read "
    "§ Context Recovery and follow it to the letter."
)


CTX_SCOPED_TASK_TEMPLATE = (
    """\
You are in a directory containing ONLY the file you need — nothing else \
exists for you, no other path is reachable or relevant:
- `transcript.txt` — recent assistant activity since the last update

You have NOT been given the current session context or project/repository \
records, and that is deliberate — report ONLY what this excerpt adds, never \
what should stay or go in records you haven't seen. Another process merges \
your additions in and handles caps/eviction; that is not your job.

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
    """transcript.txt, context.md, or memory record files themselves. Omit """
    """this heading entirely if nothing new qualifies.>
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

CTX_PROJECT_BLOCK = (
    """

# {record_kind}: {record_id}
## Status
<Current status supported by this excerpt. Omit this heading when the excerpt
does not establish a newer state. Never restate an older or superseded state.>
## Decisions
<New decisions only, one per line: `- decision — why`. Omit if none.>
"""
)

CTX_REPOSITORY_BLOCK = (
    """

# Repository: {repo_id}
## Architecture
<New architecture facts only, one `- subject — fact` per line. Omit if none.>
## Components
<New file roles only, one `- path — role` per line. Omit if none.>
## Interfaces
<New interface facts only, one `- subject — fact` per line. Omit if none.>
## Environment
<New environment facts only, one `- subject — fact` per line. Omit if none.>
"""
)

# Words no project/subproject may be named, beyond owrap's kinds, actions,
# aliases, and the `get project` facets (derived at runtime).
RESERVED_WORDS = ("all", "main", "sub", "template")
