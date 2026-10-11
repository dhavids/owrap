"""
The planner's self-service fallback for `owrap ctx`/`updr`/`uall` when
opencode is down: print which real files to update and how (same
target resolution a real dispatch would use), then let the planner
edit them directly with its own tools instead of through a model.
`done()` closes out the bookkeeping a successful dispatch would
otherwise have left behind.
"""
import os
import sys
import time

from . import state
from .dispatch import read_opencode_status_detail
from .excerpt import (
    extract_codex_excerpt_lines, extract_excerpt_lines, last_attach_ts_ns,
    latest_event_ns,
)
from ..utils.io.filelock import file_lock
from ..utils.memory.records import resolve_memory_target
from ..utils.paths import (
    claude_transcript_path, codex_transcript_path, context_path,
    ctx_state_lock_path, get_workspace_path,
)
from ..session.resolver import (
    _parse, owrap_sid_for_ccsid, owrap_sid_for_codex_session_id, session_file,
)


def template(subproject: str = None) -> None:
    """
    Print the Context/Project/Repository update instructions and the
    real file paths for the current session's target.
    """
    ccsid = os.environ.get("CLAUDE_CODE_SESSION_ID", "").strip()
    source = "claude"
    if not ccsid:
        ccsid = os.environ.get("CODEX_SESSION_ID", "").strip()
        source = "codex"
    if not ccsid:
        print("No Claude or Codex session ID — run this from an attached window")
        sys.exit(1)

    owrap_sid = (
        owrap_sid_for_codex_session_id(ccsid) if source == "codex"
        else owrap_sid_for_ccsid(ccsid)
    )
    if not owrap_sid:
        print("No owrap session attached to this window — run `owrap attach` first")
        sys.exit(1)

    sf_path = session_file(owrap_sid)
    session_data = _parse(sf_path) if sf_path.exists() else {}
    if subproject is not None and session_data.get("target_kind") == "project":
        session_data = dict(session_data)
        session_data["subproject_id"] = "" if subproject == "main" else subproject

    target = (
        resolve_memory_target(session_data)
        if session_data.get("target_kind") else None
    )

    detail = read_opencode_status_detail()
    status_line = f"opencode status: {detail['status']}"
    if detail["reason"]:
        status_line += f" ({detail['reason']})"
    print(status_line)
    print(
        "Update these files yourself, following the rules below — then "
        "run `owrap ctx done` so the next dispatch doesn't redo this.\n"
    )

    print(f"# Context — {context_path(owrap_sid)}")
    print(
        "## Focus — replace entirely with 1-3 lines on what just "
        "happened (not additive; the old text goes away)\n"
        "## Key Locations — prepend NEW `- path — reason` lines for "
        "source paths relevant to ongoing work; keep at most 5\n"
        "## Decisions — prepend NEW `- decision — why` lines; keep at "
        "most 7\n"
        "## How To — prepend NEW `- command — when to use it` lines, "
        "only for commands actually run; keep at most 3\n"
        "## Environment — replace only if venv/flags/constraints changed\n"
    )

    if target is not None:
        if target.project_path:
            record_kind = "Subproject" if target.subproject_id else "Project"
            record_id = target.subproject_id or target.project_id
            print(f"# {record_kind}: {record_id} — {target.project_path}")
            print(
                "## Status — replace only if this is a genuinely newer "
                "state than what's already there\n"
                "## Decisions — don't edit this section directly; run "
                f"`owrap decide {record_id} \"<text>\"` for each new "
                "decision\n"
            )
        for repo_id, repo_path in zip(
            target.repository_ids, target.repository_paths,
        ):
            print(f"# Repository: {repo_id} — {repo_path}")
            print(
                "## Architecture / Components / Interfaces / Environment — "
                "append NEW facts only, one `- subject — fact` per line; "
                "never restate what's already there\n"
            )
    else:
        print("No project/repository target configured for this session.")

    with file_lock(ctx_state_lock_path(owrap_sid)):
        ctx_state_data = state.read_ctx_state(owrap_sid)
        ctx_state_data["ctx"]["manual_started_ts"] = time.time()
        state.write_ctx_state(owrap_sid, ctx_state_data)

    _print_excerpt(ccsid, owrap_sid, source)


def _print_excerpt(ccsid: str, owrap_sid: str, source: str) -> None:
    """
    Print every transcript line since this window's cursor, with no
    length cap.
    """
    transcript = (
        codex_transcript_path(ccsid) if source == "codex"
        else claude_transcript_path(ccsid, get_workspace_path())
    )
    if transcript is None or not transcript.exists():
        print(f"\n(no transcript found for {source} session {ccsid})")
        return
    lines = transcript.read_text().splitlines()
    counters = state.read_window_state(owrap_sid, ccsid)
    cursor_ns = counters.get("transcript_cursor_ns", 0)
    attach_ts_ns = last_attach_ts_ns(lines, owrap_sid)
    effective_cursor_ns = max(cursor_ns, attach_ts_ns)
    texts = (
        extract_codex_excerpt_lines(lines, effective_cursor_ns)
        if source == "codex"
        else extract_excerpt_lines(lines, effective_cursor_ns)
    )
    print("\n# Transcript excerpt since the last update (not truncated)\n")
    print("\n\n".join(texts) if texts else "(nothing new since the last update)")


def done(error: str = None) -> None:
    """
    Record that the planner finished a manual context/records update
    by hand: set `ctx_status` to `ok` (or `failed`, if `error` is
    given to report the manual attempt itself failed) and advance
    this window's transcript cursor to now, the same bookkeeping a
    successful automatic dispatch leaves. Refuses to mark `ok` if
    none of the target files changed since `owrap ctx get template` ran --
    catches the planner running `done` without actually having
    edited anything.
    """
    ccsid = os.environ.get("CLAUDE_CODE_SESSION_ID", "").strip()
    source = "claude"
    if not ccsid:
        ccsid = os.environ.get("CODEX_SESSION_ID", "").strip()
        source = "codex"
    if not ccsid:
        print("No Claude or Codex session ID — run this from an attached window")
        sys.exit(1)

    owrap_sid = (
        owrap_sid_for_codex_session_id(ccsid) if source == "codex"
        else owrap_sid_for_ccsid(ccsid)
    )
    if not owrap_sid:
        print("No owrap session attached to this window — run `owrap attach` first")
        sys.exit(1)

    if not error:
        _check_manual_update_happened(owrap_sid)

    transcript = (
        codex_transcript_path(ccsid) if source == "codex"
        else claude_transcript_path(ccsid, get_workspace_path())
    )

    window_state = state.read_window_state(owrap_sid, ccsid)
    if transcript is not None and transcript.exists():
        lines = transcript.read_text().splitlines()
        latest_ts_ns = latest_event_ns(lines)
        if latest_ts_ns is not None:
            window_state["transcript_cursor_ns"] = max(
                latest_ts_ns, window_state.get("transcript_cursor_ns", 0),
            )
            state.write_window_state(owrap_sid, window_state, ccsid)

    status = "failed" if error else "ok"
    state.set_ctx_dispatch_result(owrap_sid, status, kind="manual", reason=error)
    state.clear_touched_entries(owrap_sid, ccsid)
    with file_lock(ctx_state_lock_path(owrap_sid)):
        ctx_state_data = state.read_ctx_state(owrap_sid)
        if ctx_state_data["ctx"].pop("manual_started_ts", None) is not None:
            state.write_ctx_state(owrap_sid, ctx_state_data)
    if error:
        print(f"Marked session {owrap_sid}'s manual update as failed: {error}")
    else:
        print(f"Marked session {owrap_sid}'s context update as done manually.")


def _check_manual_update_happened(owrap_sid: str) -> None:
    """
    Refuse with an error (exit 2) if `owrap ctx get template` was run for this
    session and none of its listed target files have changed since —
    the planner either hasn't edited them yet or ran `done`
    against the wrong session. No-op if `owrap ctx get template` was never run
    (nothing to compare against) or has already been cleared.
    """
    ctx_state_data = state.read_ctx_state(owrap_sid)
    started_ts = ctx_state_data["ctx"].get("manual_started_ts")
    if started_ts is None:
        return

    target_paths = [context_path(owrap_sid)]
    sf_path = session_file(owrap_sid)
    session_data = _parse(sf_path) if sf_path.exists() else {}
    target = (
        resolve_memory_target(session_data)
        if session_data.get("target_kind") else None
    )
    if target is not None:
        if target.project_path:
            target_paths.append(target.project_path)
        target_paths.extend(target.repository_paths)

    changed = any(
        p.exists() and p.stat().st_mtime > started_ts for p in target_paths
    )
    if not changed:
        print(
            "ERROR: none of the target files `owrap ctx get template` listed have "
            "changed since it ran — nothing looks actually updated. Edit "
            "the files, or pass --error \"<reason>\" if the manual "
            "update itself failed."
        )
        sys.exit(2)
