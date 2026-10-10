CTX_IDLE_TIMEOUT_S = 60

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
