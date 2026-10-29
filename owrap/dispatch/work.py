"""
The sentinel lifecycle shared by every synchronous dispatch kind
(read/task/work/agent/f): register a running unit of work, normalize
its outcome (timeout/stall/crash/success), and complete its sentinel
-- the one place this bookkeeping lives. `externally_killed` and
`stall_killed` are passed explicitly as a plain dict shared by a
SIGTERM handler and the dispatch call it interrupts.
"""
import fcntl
import json
import os
import signal
import sys
import tempfile
import time
from datetime import datetime

from .process import is_alive
from ..ctx.state import clear_running_task, register_running_task
from ..utils.session.resolver import session_label
from ..utils.constants import RECENT_TASK_RETENTION_S
from ..utils.io.atomic import write_atomic
from ..utils.io.filelock import file_lock
from ..utils.log import rtlog
from ..utils.parser.snippet import divider
from ..utils.paths import (
    RECENTLY_DONE_DIR, RUNNING_DIR, STATS_FILE, STATS_LOCK_FILE, _read_config,
    get_workspace_config,
)


def allow_all() -> bool:
    """
    True if this workspace or the global config allows opencode to
    skip its own permission prompts for a synchronous dispatch.
    """
    config = _read_config()
    ws_cfg = get_workspace_config(config.get("default_workspace", ""))
    return bool(
        config.get("runner_allow_all", False)
        or ws_cfg.get("runner_allow_all", False)
    )


# Context Injection

def should_inject_context(ctx_cfg: dict, session_id: str, cp) -> bool:
    """
    True if `cp` (a session's context.md path) is enabled, scoped to
    a real session, and non-empty -- the gating check every dispatch
    kind runs before prefixing its own prompt/content with a
    "read context.md first" instruction.
    """
    return bool(
        ctx_cfg.get("context_injection_enabled", True)
        and session_id and cp.exists() and cp.stat().st_size > 0
    )


def context_prefix(cp, executor_md=None) -> str:
    """
    An inline "read this first, then: " prefix for a single-line
    prompt, naming `executor_md` too when it exists.
    """
    if executor_md and executor_md.exists():
        return f"First read {executor_md}, then read {cp}, then: "
    return f"First read {cp}, then: "


def context_block(cp, executor_md=None) -> str:
    """
    A "## Context" block to prepend to a multi-line task file's
    content, naming `executor_md` too when it exists.
    """
    if executor_md and executor_md.exists():
        return (
            f"## Context\nFirst read {executor_md}, then read "
            f"{cp} before starting this task.\n\n"
        )
    return f"## Context\nFirst read {cp} before starting this task.\n\n"


def _increment_stat(key: str) -> None:
    """
    Atomically increment a counter in the stats file -- shares
    STATS_LOCK_FILE with Daemon._reset_stats, the file's only other
    writer.
    """
    STATS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with file_lock(STATS_LOCK_FILE):
        try:
            data = json.loads(STATS_FILE.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            data = {
                "dispatched": 0, "succeeded": 0, "failed": 0,
                "stalled": 0, "timed_out": 0,
            }
        data[key] = data.get(key, 0) + 1
        write_atomic(STATS_FILE, json.dumps(data))


def prepend_log_entry(log_path, title: str, tag: str = "") -> None:
    """
    Prepend one `<timestamp> <tag> — <title>` line to a flat history log
    (`run_log_path`/`read_log_path`/`exec_log_path`) under an flock.
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    tag_str = f" {tag}" if tag else ""
    entry = f"{datetime.now().strftime('%Y-%m-%d %H:%M')}{tag_str} — {title}\n"
    log_path.touch(exist_ok=True)
    with open(log_path, "r+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        existing = f.read()
        f.seek(0)
        f.write(entry + existing)
        f.truncate()


# Sentinel Write/Complete

def write_sentinel(
    session_id: str, task_id, title: str, kind: str = "task",
    call_type: str = "task", url: str = None, output_path=None,
):
    """
    Register one running task in RUNNING_DIR, returning its sentinel
    path.
    """
    RUNNING_DIR.mkdir(parents=True, exist_ok=True)
    session_id = session_id or "none"
    name = f"{kind}{task_id}_{session_id}.json"
    data = {
        "pid": os.getpid(),
        "task_id": str(task_id),
        "session_id": session_id,
        "kind": kind,
        "call_type": call_type,
        "title": title,
        "started": time.time(),
        "server_url": url or "",
        "output_path": str(output_path) if output_path else "",
    }
    path = RUNNING_DIR / name
    fd, tmp_path = tempfile.mkstemp(
        dir=str(RUNNING_DIR), prefix=f".{name}.", suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w") as f:
            f.write(json.dumps(data))
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    rtlog.log(
        "dispatch.start", kind=kind, label=title, url=data["server_url"],
        task_id=str(task_id),
    )
    register_running_task(session_id, name, {
        "kind": kind, "call_type": call_type, "title": title,
        "pid": data["pid"], "started": data["started"],
    })
    return path


def complete_sentinel(
    sentinel_path, rc: int, timed_out: bool = False, stalled: bool = False,
    failure_kind: str = None, raw_rc: int = None, externally_killed: bool = False,
) -> None:
    """
    Move a sentinel from RUNNING_DIR to RECENTLY_DONE_DIR with its
    outcome, and update the shared dispatch stats. No-op if
    `externally_killed` -- the SIGTERM handler's own exit path
    already left the sentinel for whoever sent the signal (`Task.done`)
    to complete instead.
    """
    if externally_killed:
        return
    if sentinel_path is None or not sentinel_path.exists():
        return
    try:
        RECENTLY_DONE_DIR.mkdir(parents=True, exist_ok=True)
        data = json.loads(sentinel_path.read_text())
        data["finished"] = time.time()
        data["rc"] = rc
        if timed_out:
            data["timed_out"] = True
        if failure_kind:
            data["failure_kind"] = failure_kind
        if raw_rc is not None and raw_rc != rc:
            data["raw_rc"] = raw_rc
        done_name = sentinel_path.name
        done_path = RECENTLY_DONE_DIR / done_name
        fd, tmp_path = tempfile.mkstemp(
            dir=str(RECENTLY_DONE_DIR), prefix=f".{done_name}.", suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w") as f:
                f.write(json.dumps(data))
            os.replace(tmp_path, done_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        sentinel_path.unlink()
        clear_running_task(data.get("session_id", ""), done_name)
    except Exception:
        pass

    _increment_stat("dispatched")
    if rc == 0:
        _increment_stat("succeeded")
    elif timed_out:
        _increment_stat("timed_out")
    elif stalled:
        _increment_stat("stalled")
    else:
        _increment_stat("failed")


def finish_dispatch(
    label: str, result: dict, watchdog, sentinel_path, log_path,
    timeout_s: float, default_timeout_s: float, state: dict = None,
) -> int:
    """
    Normalize timeout, infra-failure, and rc handling, then write the
    RESULT footer and completion sentinel. Returns the final rc.
    `state` (as set up by `new_signal_state`/`install_sigterm_handler`)
    supplies `stall_killed`/`externally_killed`; omit it if the caller
    never installed a SIGTERM handler.
    """
    state = state or {}
    timed_out = bool(result.get("timed_out"))
    stall_killed = state.get("stall_killed", False)
    raw_rc = result.get("returncode", 1)
    failure_kind = None

    if timed_out:
        partial = (result.get("stdout") or "").strip()
        print(flush=True)
        print(
            f"[{label}] timed out after {timeout_s:.0f}s "
            f"({len(partial)} chars captured)",
            flush=True,
        )
        print(
            f"  rerun with -t <seconds> to extend "
            f"(default: {default_timeout_s}s)",
            flush=True,
        )
        rc = 2
        failure_kind = "timeout"
    elif stall_killed:
        rc = raw_rc
        if watchdog is not None and not watchdog._has_output:
            if watchdog._model_logged:
                rc = 1
                failure_kind = "infra_failure"
            else:
                rc = 4
                failure_kind = "unresponsive"
        else:
            failure_kind = "stalled"
    else:
        rc = raw_rc
        if rc == 0 and watchdog is not None:
            watchdog.check_output()
            if not watchdog._has_output:
                if watchdog._model_logged:
                    rc = 1
                    failure_kind = "infra_failure"
                    watchdog.report_infra_failure()
                else:
                    rc = 4
                    failure_kind = "unresponsive"
                    watchdog.report_unresponsive()
        elif rc != 0:
            rc = 3
            failure_kind = "crashed"

    if rc == 0:
        reason = "ok"
    elif failure_kind == "crashed":
        reason = f"crashed (exit {raw_rc})"
    elif failure_kind:
        reason = failure_kind.replace("_", " ")
    else:
        reason = f"rc={rc}"
    try:
        with open(log_path, "a") as lf:
            lf.write(
                f"\n{divider('RESULT')}\n"
                f"[{datetime.now().isoformat()}] rc={rc} {reason}\n"
            )
    except Exception:
        pass

    complete_sentinel(
        sentinel_path, rc, timed_out=timed_out, stalled=stall_killed,
        failure_kind=failure_kind, raw_rc=raw_rc,
        externally_killed=state.get("externally_killed", False),
    )
    rtlog.log(
        "dispatch.end", label=label, rc=rc, raw_rc=raw_rc,
        failure_kind=failure_kind, timed_out=timed_out,
    )
    return rc


# SIGTERM Handling

def new_signal_state() -> dict:
    """
    A fresh `{"externally_killed": False, "stall_killed": False}` --
    pass the same dict to `install_sigterm_handler` and `finish_dispatch`
    so they share state without an instance to hold it on.
    """
    return {"externally_killed": False, "stall_killed": False}


def install_sigterm_handler(state: dict) -> None:
    """
    On SIGTERM, mark `state["externally_killed"]` and exit 143.
    """
    def _handler(signum, frame):
        state["externally_killed"] = True
        sys.exit(143)
    signal.signal(signal.SIGTERM, _handler)


# Status Lookup

def find_task(task_id, kind: str = None, session_id: str = None) -> dict | None:
    """
    Return the sentinel record for `task_id` -- from RUNNING_DIR if
    still running (with `alive` set from a PID liveness check), else
    from RECENTLY_DONE_DIR if already finished. None if no match.
    Narrow with `kind` (one `Dispatch` kind's own tasks only) or
    `session_id`; omit both for a cross-kind, cross-session lookup
    (what `Task.get`/`Task.done` need).
    """
    task_id = str(task_id)
    for directory, running in ((RUNNING_DIR, True), (RECENTLY_DONE_DIR, False)):
        if not directory.exists():
            continue
        for f in sorted(directory.iterdir()):
            try:
                data = json.loads(f.read_text())
            except Exception:
                continue
            if str(data.get("task_id")) != task_id:
                continue
            if kind is not None and data.get("kind") != kind:
                continue
            if session_id is not None and data.get("session_id") != session_id:
                continue
            if running:
                pid = data.get("pid")
                data["alive"] = bool(pid) and is_alive(pid)
            return data
    return None


def format_task_status(data: dict, show_session: bool = False) -> str:
    """
    One-line status for a `find_task` result (or any raw
    RUNNING_DIR/RECENTLY_DONE_DIR record).
    """
    kind = data.get("kind", "task")
    label = f"{kind}{data.get('task_id', '?')}"
    sid = data.get("session_id", "?")
    sess = f"  [{session_label(sid)}]" if show_session else ""
    out = data.get("output_path", "")
    out_str = f"  {out}" if out else ""

    if "finished" in data:
        rc = data.get("rc")
        if rc == 0:
            outcome = "ok"
        else:
            failure_kind = data.get("failure_kind")
            if failure_kind == "crashed":
                outcome = f"crashed (exit {data.get('raw_rc', rc)})"
            elif failure_kind:
                outcome = failure_kind.replace("_", " ")
            elif data.get("timed_out"):
                outcome = "timeout"
            else:
                outcome = f"rc={rc}"
        started, finished = data.get("started"), data.get("finished")
        dur = f"{finished - started:.1f}s" if started and finished else "?s"
        return f"{label}{sess}  done({outcome})  {dur}{out_str}"

    alive = data.get("alive", False)
    if not alive:
        status = "stale/crashed"
    else:
        health = data.get("health", "healthy")
        status = {
            "infra_failure": "INFRA FAILURE", "unresponsive": "UNRESPONSIVE",
            "stalled": "STALLED",
        }.get(health, "running")
    elapsed = time.time() - data.get("started", time.time())
    return f"{label}{sess}  {status}  {elapsed:.0f}s{out_str}"


# Housekeeping

def cleanup_recently_done() -> None:
    """
    Reap RUNNING_DIR sentinels whose PID has died without completing
    normally, and remove RECENTLY_DONE_DIR entries older than
    `RECENT_TASK_RETENTION_S`.
    """
    if RUNNING_DIR.exists():
        for f in list(RUNNING_DIR.iterdir()):
            try:
                data = json.loads(f.read_text())
                pid = data.get("pid")
                alive = bool(pid) and is_alive(pid)
                recent = (time.time() - f.stat().st_mtime) < 5
                if not alive and recent:
                    # Grace period, may still be completing
                    continue
                if not alive:
                    RECENTLY_DONE_DIR.mkdir(parents=True, exist_ok=True)
                    done_path = RECENTLY_DONE_DIR / f.name
                    if done_path.exists():
                        # Already completed; don't clobber
                        f.unlink()
                        continue
                    data["finished"] = time.time()
                    data["rc"] = 143
                    data["failure_kind"] = "reaped"
                    done_path.write_text(json.dumps(data))
                    f.unlink()
                    age_s = round(time.time() - data.get("started", time.time()))
                    rtlog.log(
                        "dispatch.reap", task_id=data.get("task_id"), age_s=age_s,
                    )
            except Exception:
                pass

    if not RECENTLY_DONE_DIR.exists():
        return
    cutoff = time.time() - RECENT_TASK_RETENTION_S
    for f in RECENTLY_DONE_DIR.iterdir():
        try:
            data = json.loads(f.read_text())
            if data.get("finished", 0) < cutoff:
                f.unlink()
        except Exception:
            pass
