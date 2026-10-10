"""
Read/write access to a session's ctx_state.json: attached windows,
per-window transcript cursors and touched-path queues, currently-
running dispatch tasks, and the session-level ctx dispatch status.
"""
import json
import os
import time

from ..session.resolver import owrap_sid_for_ccsid, owrap_sid_for_codex_session_id
from ..utils.io.filelock import file_lock
from ..utils.parser.text import age_str
from ..utils.paths import (
    ctx_state_lock_path, session_ctx_counters_path, session_ctx_state_path,
    session_ctx_touched_path,
)


def register_ctx_state_window(
    session_id: str, window_id: str, harness: str = "claude",
) -> None:
    """
    Ensure one window has an entry in the session's ctx_state.json, on
    `owrap attach` — so the windows map (the source of "all attached
    windows" for this session) reflects reality from the moment a
    window attaches, not only once it first dispatches/touches/done()s.
    Never clobbers an existing entry's cursor/touched state; only adds
    `harness` and `attached_ts` if the window is new.
    """
    if not window_id:
        return
    p = session_ctx_state_path(session_id)
    with file_lock(ctx_state_lock_path(session_id)):
        state = {"windows": {}}
        if p.exists():
            try:
                with open(p) as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    state = loaded
                    state.setdefault("windows", {})
            except (json.JSONDecodeError, OSError):
                pass
        window = state["windows"].setdefault(window_id, {})
        window.setdefault("harness", harness)
        window.setdefault("attached_ts", time.time())
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w") as f:
            json.dump(state, f)


def prune_ctx_state_window(session_id: str, window_id: str) -> None:
    """
    Remove one window's entry from the session's ctx_state.json, on
    `owrap detach` — a detached window no longer needs its transcript
    cursor tracked, and "all attached windows" (the windows map's keys)
    should only list windows actually still attached.
    """
    if not window_id:
        return
    p = session_ctx_state_path(session_id)
    with file_lock(ctx_state_lock_path(session_id)):
        if not p.exists():
            return
        try:
            with open(p) as f:
                state = json.load(f)
        except (json.JSONDecodeError, OSError):
            return
        if not isinstance(state, dict) or window_id not in state.get("windows", {}):
            return
        state["windows"].pop(window_id, None)
        with open(p, "w") as f:
            json.dump(state, f)


def append_touched_entries(session_id: str, ccsid: str, entries: list) -> int:
    """
    Append `owrap touched` entries to a window's slice of the session's
    ctx_state.json, for the next context-manager dispatch to pick up.
    Returns the window's new total entry count.
    """
    p = session_ctx_state_path(session_id)
    with file_lock(ctx_state_lock_path(session_id)):
        state = {"windows": {}}
        if p.exists():
            try:
                with open(p) as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    state = loaded
                    state.setdefault("windows", {})
            except (json.JSONDecodeError, OSError):
                pass
        window = state["windows"].setdefault(ccsid, {})
        touched = window.setdefault("touched", [])
        touched.extend(entries)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w") as f:
            json.dump(state, f)
        return len(touched)


def queue_touched_paths(paths: tuple, note: str = None) -> int:
    """
    Queue touched file paths for the next ctx/updr dispatch from this
    window's attached session, each with the same optional one-line
    note. Returns the number of paths queued. Shared by `Ctx.add` and
    `Updr.add` -- both feed the same `_dispatch` touched-entry queue.
    """
    if not paths:
        raise ValueError("no paths given")
    ccsid = os.environ.get("CLAUDE_CODE_SESSION_ID", "").strip()
    source = "claude"
    if not ccsid:
        ccsid = os.environ.get("CODEX_SESSION_ID", "").strip()
        source = "codex"
    if not ccsid:
        raise ValueError(
            "no Claude or Codex session ID — run this from an attached window"
        )
    owrap_sid = (
        owrap_sid_for_codex_session_id(ccsid) if source == "codex"
        else owrap_sid_for_ccsid(ccsid)
    )
    if not owrap_sid:
        raise ValueError(
            "no owrap session attached to this window — run "
            "`owrap session attach` first"
        )
    entries = [{"path": path, "note": note or ""} for path in paths]
    append_touched_entries(owrap_sid, ccsid, entries)
    return len(paths)


def _rw_ctx_state_running(session_id: str, mutate) -> None:
    """
    Shared read-mutate-write for the session's `running` map (currently
    dispatched msg/task/exec/agent calls, keyed by task_id) in
    ctx_state.json. `mutate(running_dict)` edits in place.
    """
    p = session_ctx_state_path(session_id)
    with file_lock(ctx_state_lock_path(session_id)):
        state = {"windows": {}}
        if p.exists():
            try:
                with open(p) as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    state = loaded
                    state.setdefault("windows", {})
            except (json.JSONDecodeError, OSError):
                pass
        running = state.setdefault("running", {})
        mutate(running)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w") as f:
            json.dump(state, f)


def register_running_task(session_id: str, task_id: str, info: dict) -> None:
    """
    Record one currently-dispatched msg/task/exec/agent call in the
    session's ctx_state.json — so "what's running for this session"
    (there can be several at once) is queryable without globbing
    RUNNING_DIR for sentinel files.
    """
    if not session_id or session_id == "none":
        return
    _rw_ctx_state_running(
        session_id, lambda running: running.update({task_id: info}),
    )


def clear_running_task(session_id: str, task_id: str) -> None:
    """
    Remove one task from the session's running map once it completes.
    """
    if not session_id or session_id == "none":
        return
    _rw_ctx_state_running(
        session_id, lambda running: running.pop(task_id, None),
    )


def read_ctx_state(session_id: str) -> dict:
    """
    Read this session's whole ctx_state.json: a `ctx` sub-object
    (status, last_dispatch, manual_started_ts), per-target sync
    state, and the windows map (one entry per attached window's
    transcript cursor). An empty skeleton if the file doesn't exist
    yet or is unreadable.
    """
    p = session_ctx_state_path(session_id)
    if p.exists():
        try:
            with open(p) as f:
                data = json.load(f)
            if isinstance(data, dict):
                data.setdefault("windows", {})
                data.setdefault("ctx", {})
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return {"windows": {}, "ctx": {}}


def ctx_dispatch_status(session_id: str) -> str:
    """
    Return this session's last ctx/updr dispatch status -- "running"
    while one is in flight (`set_ctx_dispatch_result`'s "pending"),
    else "ok"/"failed", or "never run" if none has happened yet.
    Shared by `Ctx.get`/`Updr.get` -- one combined status per
    session, not kind-specific, since a dispatch can cover context,
    protocol, or both at once.
    """
    status = read_ctx_state(session_id).get("ctx", {}).get("status")
    return "running" if status == "pending" else (status or "never run")


def ctx_last_dispatch(session_id: str) -> dict:
    """
    Return this session's last *completed* dispatch record --
    `{ts, kind, status, model, reason}`, `set_ctx_dispatch_result`'s
    own shape -- or `{}` if none has completed yet.
    """
    return read_ctx_state(session_id).get("ctx", {}).get("last_dispatch") or {}


def format_last_dispatch(session_id: str) -> str:
    """
    Format "last run: <age> ago (<model>)" from this session's last
    completed dispatch, with its failure reason appended if it
    failed, or "" if none has completed yet. Shared by `Ctx.get`/
    `Updr.get` for the same reason `ctx_dispatch_status` is: one
    combined record per session, not kind-specific.
    """
    last = ctx_last_dispatch(session_id)
    if not last.get("ts"):
        return ""
    line = f"last run: {age_str(last['ts'])} ago"
    if last.get("model"):
        line += f" ({last['model']})"
    if last.get("status") == "failed" and last.get("reason"):
        line += f" — {last['reason']}"
    return line


def write_ctx_state(session_id: str, data: dict) -> None:
    p = session_ctx_state_path(session_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w") as f:
        json.dump(data, f)


def read_window_state(session_id: str, ccsid: str) -> dict:
    """
    Read one window's slice (transcript cursor, touched entries) of
    the session's ctx_state.json, migrating its old standalone
    counters.json/touched.json in on first read if this window
    hasn't been folded in yet.
    """
    with file_lock(ctx_state_lock_path(session_id)):
        state = read_ctx_state(session_id)
        if ccsid not in state["windows"]:
            window = {}
            old_counters = session_ctx_counters_path(session_id, ccsid)
            if old_counters.exists():
                try:
                    with open(old_counters) as f:
                        old_data = json.load(f)
                    if isinstance(old_data, dict):
                        window.update(old_data)
                except (json.JSONDecodeError, OSError):
                    pass
            old_touched = session_ctx_touched_path(session_id, ccsid)
            if old_touched.exists():
                try:
                    with open(old_touched) as f:
                        old_touched_data = json.load(f)
                    if isinstance(old_touched_data, list):
                        window["touched"] = old_touched_data
                except (json.JSONDecodeError, OSError):
                    pass
            if window:
                state["windows"][ccsid] = window
                write_ctx_state(session_id, state)
        return dict(state["windows"].get(ccsid, {}))


def write_window_state(session_id: str, data: dict, ccsid: str) -> None:
    with file_lock(ctx_state_lock_path(session_id)):
        state = read_ctx_state(session_id)
        state["windows"][ccsid] = data
        write_ctx_state(session_id, state)


def set_ctx_dispatch_result(
    session_id: str, status: str, kind: str = None,
    model: str = None, reason: str = None,
) -> None:
    """
    Record ctx_status and the last dispatch's outcome in the
    session-level ctx_state.json — the single source of truth
    orientation.py reads, instead of a line regexed out of
    context.md's prose.
    """
    with file_lock(ctx_state_lock_path(session_id)):
        state = read_ctx_state(session_id)
        state["ctx"]["status"] = status
        state["ctx"]["last_dispatch"] = {
            "ts": time.time(), "kind": kind, "status": status,
            "model": model, "reason": reason,
        }
        write_ctx_state(session_id, state)


def load_touched_entries(session_id: str, ccsid: str) -> list:
    """
    Return this window's pending `owrap touched` entries, each
    `{"path": ..., "note": ...}`. Empty list if none are queued.
    """
    return read_window_state(session_id, ccsid).get("touched", [])


def clear_touched_entries(session_id: str, ccsid: str) -> None:
    """
    Clear this window's pending-touched entries after they've been
    successfully applied. Also removes the legacy standalone
    touched.json if a migration-on-read left it behind unread.
    """
    session_ctx_touched_path(session_id, ccsid).unlink(missing_ok=True)
    with file_lock(ctx_state_lock_path(session_id)):
        state = read_ctx_state(session_id)
        window = state["windows"].get(ccsid)
        if window and "touched" in window:
            window.pop("touched", None)
            write_ctx_state(session_id, state)
