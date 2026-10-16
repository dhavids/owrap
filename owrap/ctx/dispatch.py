"""
Context-manager dispatch: extracts new assistant transcript text for one
attached window (ccsid) and dispatches an Update Context / Update
Protocol task to the configured model.

Three entry points share the same `_dispatch` core:
- `run(input_path)` — background worker spawned by `hook_run` on
  Claude Code's PreCompact hook; always does both Context and Protocol.
- `run_manual(mode, subproject)` — fire-and-forget dispatch for the
  planner's `--ctx`/`--updr` commands: validates fast, queues the
  requested half on a detached `ctx` process, returns immediately.
- `check_all_attached()` — background trigger check from the daemon's
  loop; dispatches both halves for every window with a non-empty diff.
"""
import contextlib
import json
import math
import os
import re
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from . import state
from .excerpt import (
    extract_codex_excerpt_lines, extract_excerpt_lines, fmt_ts_ns,
    has_recognized_transcript_entries, last_attach_ts_ns, latest_event_ns,
    lines_up_to_ceiling,
)
from .records import apply_record_output, validate_output
from .templates import (
    CTX_CONTEXT_BLOCK, CTX_IDLE_TIMEOUT_AFTER_READ_S, CTX_IDLE_TIMEOUT_S,
    CTX_PROJECT_BLOCK, CTX_READ_MARKER, CTX_REPOSITORY_BLOCK,
    CTX_SCOPED_TASK_TEMPLATE,
)
from ..utils.constants import ANTI_SUMMARY_SUFFIX
from ..utils.dispatch.terminal import Terminal
from ..utils.dispatch.watchdog import strip_boilerplate
from ..utils.io.atomic import write_atomic
from ..utils.io.filelock import file_lock
from ..utils.log import context_jobs, rtlog
from ..utils.memory.records import (
    is_high_risk_session, register_discovered_repositories,
    resolve_memory_target, touched_repository_paths,
)
from ..utils.parser.output import OutputParser
from ..utils.paths import (
    OPENCODE_STATUS_FILE, RUNTIME_DIR, claude_transcript_path,
    codex_transcript_path, context_path, get_model_chain, get_workspace_path,
    session_ctx_dir, session_ctx_transcript_path, _read_config,
)
from ..session.resolver import (
    _parse, all_attached_ccsid_pairs, all_attached_codex_session_id_pairs,
    detach_window, owrap_sid_for_ccsid, owrap_sid_for_codex_session_id,
    session_file,
)

MAX_EXCERPT_CHARS = 40000
MAX_CODEX_EXCERPT_CHARS = 40000

# Applies everywhere; a real model call needs both, not either.
CTX_MIN_INTERVAL_S = 300  # 5 min since this window's last real attempt
CTX_MIN_CHARS = 5000  # excerpt must also clear this
AUTO_CTX_STATE_FILE = RUNTIME_DIR / "auto_ctx_backoff.json"
AUTO_CTX_FAILS_BEFORE_BACKOFF = 3
AUTO_CTX_BACKOFF_SCHEDULE_S = (900, 3600, 7200)  # 15m, 1h, 2h, then back to 15m
STALE_WINDOW_DAYS = 7  # auto-detach a window idle (or transcript-less) this long


def read_opencode_status_detail() -> dict:
    """
    Return the shared opencode health flag as {"status", "reason",
    "since"} — "up"/no reason if the flag has never been written.
    """
    try:
        data = json.loads(OPENCODE_STATUS_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return {"status": "up", "reason": None, "since": None}
    return {
        "status": data.get("status", "up"),
        "reason": data.get("reason"),
        "since": data.get("since"),
    }


def read_opencode_status() -> str:
    """
    Return "down" if the shared opencode health flag says every model in
    the chain is currently timing out, "up" otherwise (including when the
    flag has never been written).
    """
    return read_opencode_status_detail()["status"]


def _write_opencode_status(status: str, reason: str = None) -> None:
    """
    Record the shared opencode health flag: "up" after any dispatch gets
    valid output from a model, "down" when every attempted model failed
    for any reason (timeout, transport error, subscription required,
    etc). A single flag, not per-session — the opencode account/binary
    being unreachable isn't scoped to one project. `reason` describes
    any failed write and is always cleared on an "up" write.
    """
    OPENCODE_STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(OPENCODE_STATUS_FILE, json.dumps({
        "status": status, "reason": reason,
        "since": datetime.now(timezone.utc).isoformat(),
    }))


def _read_auto_ctx_backoff() -> dict:
    try:
        return json.loads(AUTO_CTX_STATE_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return {"consecutive_fails": 0, "backoff_index": -1, "last_attempt_ts": 0.0}


def _write_auto_ctx_backoff(data: dict) -> None:
    AUTO_CTX_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    AUTO_CTX_STATE_FILE.write_text(json.dumps(data))


def _auto_ctx_due(now: float) -> bool:
    """
    Whether the daemon's background ctx check should run at all
    right now, per the base cadence or the current backoff step. A
    manual `--ctx`/`--updr` dispatch and the PreCompact hook ignore
    this entirely.
    """
    backoff = _read_auto_ctx_backoff()
    if backoff.get("consecutive_fails", 0) < AUTO_CTX_FAILS_BEFORE_BACKOFF:
        interval = AUTO_CTX_BACKOFF_SCHEDULE_S[0]
    else:
        index = max(backoff.get("backoff_index", 0), 0) % len(AUTO_CTX_BACKOFF_SCHEDULE_S)
        interval = AUTO_CTX_BACKOFF_SCHEDULE_S[index]
    return now - backoff.get("last_attempt_ts", 0) >= interval


def _record_auto_ctx_outcome(success: bool, now: float) -> None:
    """
    Update the background-ctx backoff state after a real dispatch
    attempt (not a skip for being too soon/too small). A success
    clears the backoff entirely; a failure advances the schedule
    once `AUTO_CTX_FAILS_BEFORE_BACKOFF` consecutive failures have
    accumulated.
    """
    if success:
        _write_auto_ctx_backoff(
            {"consecutive_fails": 0, "backoff_index": -1, "last_attempt_ts": now},
        )
        return
    backoff = _read_auto_ctx_backoff()
    fails = backoff.get("consecutive_fails", 0) + 1
    index = backoff.get("backoff_index", -1)
    if fails >= AUTO_CTX_FAILS_BEFORE_BACKOFF:
        index = (index + 1) % len(AUTO_CTX_BACKOFF_SCHEDULE_S)
    _write_auto_ctx_backoff(
        {"consecutive_fails": fails, "backoff_index": index, "last_attempt_ts": now},
    )


def _ctx_window_recently_attempted(owrap_sid: str, ccsid: str, now: float) -> bool:
    """
    Cheap read-only check so the background loop skips creating a job
    for a window `_dispatch` would immediately gate anyway -- purely
    an optimization. `_dispatch` itself is the authoritative,
    universal check (it also applies to manual/PreCompact dispatches,
    which never go through `check_all_attached` at all).
    """
    counters = state.read_window_state(owrap_sid, ccsid)
    return now - counters.get("last_ctx_attempt_ts", 0) < CTX_MIN_INTERVAL_S


def _pending_excerpt_len(
    owrap_sid: str, ccsid: str, transcript_lines: list, source: str,
) -> int:
    """
    Cheaply measure how many chars of new, not-yet-summarized content
    this window has -- no sandbox, no job, no model. Lets the
    background loop skip queuing a job outright for a window
    `_dispatch` would gate on CTX_MIN_CHARS anyway.
    """
    counters = state.read_window_state(owrap_sid, ccsid)
    attach_ts_ns = last_attach_ts_ns(transcript_lines, owrap_sid)
    effective_cursor_ns = max(counters.get("transcript_cursor_ns", 0), attach_ts_ns)
    extractor = (
        extract_codex_excerpt_lines if source == "codex" else extract_excerpt_lines
    )
    new_assistant_texts = extractor(transcript_lines, effective_cursor_ns)
    touched_lines = [
        f"[Touched] {e['path']}" + (f" — {e['note']}" if e.get("note") else "")
        for e in state.load_touched_entries(owrap_sid, ccsid)
    ]
    return len("\n\n".join(new_assistant_texts + touched_lines))


def run(input_path: Path = None) -> int:
    """
    Execute a context-manager worker run from the given hook-payload
    path. `mode`/target override in the payload are optional — absent (the real
    PreCompact hook payload) means both Context and Protocol, same as
    always; present (a manual `--ctx`/`--updr` handoff) restricts to
    the requested half.
    """
    if input_path is None:
        print("ctx-worker: --input required", file=sys.stderr)
        sys.exit(1)

    hook_data = json.loads(input_path.read_text())
    job_dir = Path(hook_data["job_dir"]) if hook_data.get("job_dir") else None
    config = _read_config()
    if not config.get("owrap_context_manager_enabled", True):
        print("ctx-worker: context manager disabled, skipping")
        if job_dir:
            context_jobs.finish(job_dir, 1)
        return 1

    ccsid = hook_data.get("session_id", "")
    source = hook_data.get("source", "claude")
    transcript_path = hook_data.get("transcript_path", "")
    mode = hook_data.get("mode")
    subproject = hook_data.get("subproject")
    cursor_ceiling_ns = hook_data.get("cursor_ceiling_ns")

    if source == "codex":
        owrap_sid = owrap_sid_for_codex_session_id(ccsid)
    else:
        owrap_sid = owrap_sid_for_ccsid(ccsid)
    if not owrap_sid:
        print("ctx-worker: no matching owrap session", file=sys.stderr)
        if job_dir:
            context_jobs.finish(job_dir, 1)
        return 1

    if job_dir:
        context_jobs.update(
            job_dir, status="running", started=time.time(),
            pid=os.getpid(), stage="reading transcript",
        )
    rc = 1
    try:
        ctx_dir = session_ctx_dir(owrap_sid, ccsid)
        if job_dir:
            context_jobs.update(job_dir, stage="waiting for window")
        with file_lock(ctx_dir / "dispatch.lock"):
            if job_dir:
                context_jobs.update(job_dir, stage="reading transcript")
            rc = _dispatch_tracked(
                owrap_sid, ccsid, transcript_path, config,
                do_context=(mode != "updr"), do_protocol=(mode != "ctx"),
                subproject_override=subproject,
                source=source,
                cursor_ceiling_ns=cursor_ceiling_ns,
                job_dir=job_dir,
            )
    except Exception:
        if job_dir:
            context_jobs.finish(job_dir, 1)
        raise
    if job_dir:
        context_jobs.finish(job_dir, rc)
    return rc


def run_manual(mode: str = None, subproject: str = None) -> None:
    """
    Fire-and-forget dispatch for the planner's `--ctx`/`--updr`/
    `--ctxupdr` commands: validates fast, queues the actual dispatch on
    a detached background process, and returns immediately — a model
    dispatch can take minutes, and the planner shouldn't block on it.
    Result shows up later as `ctx_status` in context.md, surfaced
    automatically in the orientation banner on the next `owrap
    refresh`/`owrap attach`.

    mode: "ctx" (Update Context only), "updr" (Update Protocol only),
    or None (both, in one dispatch — cheaper than calling `--ctx` then
    `--updr` separately, which would read the same unconsumed
    transcript excerpt twice and dispatch it twice).
    subproject: optional override for a project session's subproject;
    defaults to the session's target.
    """
    config = _read_config()
    if not config.get("owrap_context_manager_enabled", True):
        print("context manager disabled (owrap_context_manager_enabled=false)")
        sys.exit(1)

    ccsid = os.environ.get("CLAUDE_CODE_SESSION_ID", "").strip()
    source = "claude"
    if not ccsid:
        ccsid = os.environ.get("CODEX_SESSION_ID", "").strip()
        source = "codex"
    if not ccsid:
        print("No Claude or Codex session ID — run this from an attached window")
        sys.exit(1)

    if source == "codex":
        owrap_sid = owrap_sid_for_codex_session_id(ccsid)
    else:
        owrap_sid = owrap_sid_for_ccsid(ccsid)
    if not owrap_sid:
        print("No owrap session attached to this window — run `owrap attach` first")
        sys.exit(1)

    transcript = (
        codex_transcript_path(ccsid) if source == "codex"
        else claude_transcript_path(ccsid, get_workspace_path())
    )
    if transcript is None or not transcript.exists():
        print(f"No transcript found for {source} session {ccsid}")
        sys.exit(1)
    transcript_path = str(transcript)
    # Bound the dispatch to now, not whenever it clears dispatch.lock.
    cursor_ceiling_ns = latest_event_ns(transcript.read_text().splitlines())

    sf_path = session_file(owrap_sid)
    d = _parse(sf_path) if sf_path.exists() else {}
    if is_high_risk_session(d):
        print(
            "This session's project/subproject is marked high-risk -- "
            "auto-dispatch to a model is disabled. Run `owrap ctx get "
            "template`, update the files by hand, then `owrap ctx done`.",
        )
        sys.exit(1)

    kind = None
    if mode != "ctx":
        kind = d.get("target_kind")
        if kind == "project":
            target_data = dict(d)
            if subproject is not None:
                target_data["subproject_id"] = (
                    "" if subproject == "main" else subproject
                )
            try:
                resolve_memory_target(target_data)
            except (FileNotFoundError, ValueError) as exc:
                print(f"updr: {exc}", file=sys.stderr)
                sys.exit(1)
        elif kind == "repository":
            if subproject is not None:
                print(
                    "updr: repository sessions have no subproject",
                    file=sys.stderr,
                )
                sys.exit(1)
            try:
                resolve_memory_target(d)
            except (FileNotFoundError, ValueError) as exc:
                print(f"updr: {exc}", file=sys.stderr)
                sys.exit(1)
        else:
            print(
                "updr: no project or repository target configured for "
                "this session"
            )
            sys.exit(1)

    ctx_dir = session_ctx_dir(owrap_sid, ccsid)
    ctx_dir.mkdir(parents=True, exist_ok=True)
    label = "uall" if mode is None else mode
    job_dir = context_jobs.create(owrap_sid, ccsid, label)
    payload_path = job_dir / "manual.json"
    payload_path.write_text(json.dumps({
        "session_id": ccsid, "transcript_path": transcript_path,
        "mode": mode,
        "subproject": subproject if kind == "project" else None,
        "source": source,
        "job_dir": str(job_dir),
        "cursor_ceiling_ns": cursor_ceiling_ns,
    }))

    log_path = job_dir / "output.log"
    log_fd = open(str(log_path), "a")
    try:
        process = subprocess.Popen(
            [sys.executable, "-m", "owrap.kind.dispatch.ctx",
             "--input", str(payload_path)],
            stdout=log_fd, stderr=log_fd,
            start_new_session=True, close_fds=True,
            cwd=str(Path(__file__).resolve().parents[2]),
        )
    except Exception:
        context_jobs.finish(job_dir, 1)
        raise
    finally:
        log_fd.close()
    if isinstance(process.pid, int):
        context_jobs.update(job_dir, pid=process.pid)
    label = mode or "ctx+updr"
    print(
        f"{label} dispatch queued as job {job_dir.name} — check `owrap stat` "
        f"or follow {log_path}",
    )


def wait_for_job(job_id: str, timeout: int = None) -> dict:
    """
    Block until `job_id` (as `run_manual` printed it) leaves
    `queued`/`running`, polling every 0.5s, or fail once `timeout`
    seconds pass (default 300).
    """
    deadline = time.time() + (int(timeout) if timeout else 300)
    while time.time() < deadline:
        job = context_jobs.get(job_id)
        if job is None:
            raise ValueError(f"no such ctx job: {job_id}")
        if job.get("status") not in ("queued", "running"):
            return job
        time.sleep(0.5)
    raise ValueError(f"timed out waiting for ctx job {job_id}")


def _dispatch_and_track(
    owrap_sid, ccsid, transcript_path, config, source="claude", is_auto=False,
    transcript_lines: list = None,
):
    """
    Create a job, run `_dispatch_tracked` under it with full
    create/running/finish bookkeeping, and finish the job no matter
    what. Runs in-process, so its own print()s are explicitly
    redirected into the job's output.log for the duration.

    transcript_lines, if the caller already read the file, avoids a
    second full read of what can be a very large transcript.
    """
    job_dir = context_jobs.create(owrap_sid, ccsid, "auto")
    context_jobs.update(
        job_dir, status="running", started=time.time(), pid=os.getpid(),
        stage="reading transcript",
    )
    rc = 1
    try:
        ctx_dir = session_ctx_dir(owrap_sid, ccsid)
        with (job_dir / "output.log").open("a") as log_fd:
            with contextlib.redirect_stdout(log_fd), contextlib.redirect_stderr(log_fd):
                with file_lock(ctx_dir / "dispatch.lock"):
                    rc = _dispatch_tracked(
                        owrap_sid, ccsid, transcript_path, config,
                        do_context=True, do_protocol=True, source=source,
                        job_dir=job_dir, is_auto=is_auto,
                        transcript_lines=transcript_lines,
                    )
    finally:
        context_jobs.finish(job_dir, rc)


def _is_high_risk_sid(owrap_sid: str) -> bool:
    sf_path = session_file(owrap_sid)
    d = _parse(sf_path) if sf_path.exists() else {}
    return is_high_risk_session(d)


def check_all_attached() -> None:
    """
    Background trigger check: for every currently-attached Claude or
    Codex window, dispatch an Update Context / Update Protocol pass if
    its transcript has grown since its last checkpoint. Cheap to call
    on a timer — `_dispatch` itself exits before touching the model
    when a window's excerpt since its checkpoint is empty, so a window
    with nothing new costs only a transcript line-count check.

    A high-risk window is excluded before it's even counted. Gated
    three further ways before a job is ever created: `_auto_ctx_due`
    holds off entirely while backing off from repeated opencode-down
    failures; `_ctx_window_recently_attempted` skips a window inside
    its own cooldown; `_pending_excerpt_len` skips a window whose new
    content wouldn't clear `CTX_MIN_CHARS` anyway. Both the interval
    and the size gate must pass, not either -- `_dispatch` itself
    re-checks both (it's the authoritative, universal version, since
    it also covers manual/PreCompact dispatches that never reach this
    function), but checking here too means a window with nothing new
    never gets a job/rtlog entry at all instead of a trivial one.

    Called from the daemon loop; never raises — one window's failure
    is logged and skipped rather than blocking every other window.
    Always logs one `ctx.check` summary event, even when every window
    is skipped, so every tick is visible in rtlog.
    """
    config = _read_config()
    if not config.get("owrap_context_manager_enabled", True):
        return
    now = time.time()
    if not _auto_ctx_due(now):
        rtlog.log("ctx.check", backoff=True)
        return
    workspace = get_workspace_path()
    windows = dispatched = cooldown = too_small = 0
    for ccsid, owrap_sid in all_attached_ccsid_pairs():
        if _is_high_risk_sid(owrap_sid):
            continue
        windows += 1
        try:
            transcript_path = claude_transcript_path(ccsid, workspace)
            if not transcript_path.exists():
                continue
            if _ctx_window_recently_attempted(owrap_sid, ccsid, now):
                cooldown += 1
                continue
            transcript_lines = transcript_path.read_text().splitlines()
            pending = _pending_excerpt_len(owrap_sid, ccsid, transcript_lines, "claude")
            if pending < CTX_MIN_CHARS:
                too_small += 1
                continue
            dispatched += 1
            _dispatch_and_track(
                owrap_sid, ccsid, str(transcript_path), config, is_auto=True,
                transcript_lines=transcript_lines,
            )
        except Exception as e:
            print(
                f"ctx-worker: background check failed for ccsid={ccsid}: {e}",
                file=sys.stderr,
            )
    for cid, owrap_sid in all_attached_codex_session_id_pairs():
        if _is_high_risk_sid(owrap_sid):
            continue
        windows += 1
        try:
            transcript_path = codex_transcript_path(cid)
            if transcript_path is None or not transcript_path.exists():
                continue
            if _ctx_window_recently_attempted(owrap_sid, cid, now):
                cooldown += 1
                continue
            transcript_lines = transcript_path.read_text().splitlines()
            pending = _pending_excerpt_len(owrap_sid, cid, transcript_lines, "codex")
            if pending < CTX_MIN_CHARS:
                too_small += 1
                continue
            dispatched += 1
            _dispatch_and_track(
                owrap_sid, cid, str(transcript_path), config, source="codex",
                is_auto=True, transcript_lines=transcript_lines,
            )
        except Exception as e:
            print(
                f"ctx-worker: background check failed for codex sid={cid}: {e}",
                file=sys.stderr,
            )
    rtlog.log(
        "ctx.check", backoff=False, windows=windows, dispatched=dispatched,
        cooldown=cooldown, too_small=too_small,
    )


def _is_stale_window(transcript_path) -> bool:
    """
    True if `transcript_path` doesn't exist, or hasn't been touched
    in `STALE_WINDOW_DAYS` -- checked by mtime, no file content read.
    """
    if transcript_path is None or not transcript_path.exists():
        return True
    age_s = time.time() - transcript_path.stat().st_mtime
    return age_s > STALE_WINDOW_DAYS * 86400


def detach_stale_attached() -> None:
    """
    Detach every currently-attached Claude or Codex window whose
    transcript is stale or missing -- the pointer only, same as a
    manual `owrap detach`. The underlying session is untouched and
    re-attaches normally on the next `owrap refresh`/`attach`.

    Called from the daemon loop; never raises -- one window's
    failure is logged and skipped rather than blocking the rest.
    Always logs one `ctx.stale_sweep` summary event.
    """
    config = _read_config()
    if not config.get("owrap_context_manager_enabled", True):
        return
    workspace = get_workspace_path()
    windows = detached = 0
    for ccsid, owrap_sid in all_attached_ccsid_pairs():
        windows += 1
        try:
            transcript_path = claude_transcript_path(ccsid, workspace)
            if _is_stale_window(transcript_path):
                detach_window(ccsid, owrap_sid, source="claude")
                detached += 1
        except Exception as e:
            print(
                f"ctx-worker: stale sweep failed for ccsid={ccsid}: {e}",
                file=sys.stderr,
            )
    for cid, owrap_sid in all_attached_codex_session_id_pairs():
        windows += 1
        try:
            transcript_path = codex_transcript_path(cid)
            if _is_stale_window(transcript_path):
                detach_window(cid, owrap_sid, source="codex")
                detached += 1
        except Exception as e:
            print(
                f"ctx-worker: stale sweep failed for codex sid={cid}: {e}",
                file=sys.stderr,
            )
    rtlog.log("ctx.stale_sweep", windows=windows, detached=detached)


def _dispatch_tracked(
    owrap_sid, ccsid, transcript_path, config,
    do_context, do_protocol,
    subproject_override=None, source="claude", cursor_ceiling_ns=None,
    job_dir=None, is_auto=False, transcript_lines: list = None,
) -> int:
    """
    Run `_dispatch` with ctx_status tracking in ctx_state.json: pending
    before, ok on clean success, failed on any error, including an
    uncaught exception — so a crash in our own code shows up too, not
    just a failed model dispatch. Also updates the background-ctx
    backoff state (`_record_auto_ctx_outcome`) for any real model
    attempt (not a too-soon/too-small skip) -- a background failure
    advances the backoff schedule, and any success (background,
    manual, or PreCompact) clears it.
    """
    kind = "context+protocol" if do_context and do_protocol else (
        "context" if do_context else "protocol"
    )
    state.set_ctx_dispatch_result(owrap_sid, "pending")
    try:
        rc, reason, model = _dispatch(
            owrap_sid, ccsid, transcript_path, config,
            do_context=do_context, do_protocol=do_protocol,
            subproject_override=subproject_override,
            source=source, cursor_ceiling_ns=cursor_ceiling_ns,
            job_dir=job_dir, transcript_lines=transcript_lines,
        )
    except Exception as e:
        state.set_ctx_dispatch_result(owrap_sid, "failed", kind=kind, reason=str(e))
        raise
    attempted = reason is not None or model is not None
    if attempted and (is_auto or rc == 0):
        _record_auto_ctx_outcome(success=(rc == 0), now=time.time())
    state.set_ctx_dispatch_result(
        owrap_sid, "ok" if rc == 0 else "failed",
        kind=kind, model=model, reason=reason,
    )
    return rc


def _dispatch(
    owrap_sid, ccsid, transcript_path, config,
    do_context, do_protocol,
    subproject_override=None, source="claude", cursor_ceiling_ns=None,
    job_dir=None, transcript_lines: list = None,
) -> tuple:
    """
    Build the scoped sandbox, dispatch to the model, and apply its
    output back to the session context and explicit memory records.

    cursor_ceiling_ns, if given, bounds the transcript to what existed
    when the dispatch was triggered, not whatever has accumulated by
    the time this runs — it may have sat behind dispatch.lock.
    transcript_lines, if the caller already read the file, avoids a
    second full read of what can be a very large transcript.

    Every caller -- background, manual, PreCompact -- is held to the
    same floor before a real model call: at least `CTX_MIN_INTERVAL_S`
    since this window's last real attempt, and an excerpt of at least
    `CTX_MIN_CHARS`. Both are required, not either.

    Returns (returncode, reason, model) — returncode is 0 if nothing
    needed summarizing or on success; reason explains a failure;
    model is the one that produced the successful output.
    """
    session_data = {}
    sf_path = session_file(owrap_sid)
    if sf_path.exists():
        session_data = _parse(sf_path)
    if subproject_override is not None:
        if session_data.get("target_kind") == "project":
            session_data["subproject_id"] = (
                "" if subproject_override == "main"
                else subproject_override
            )

    target = (
        resolve_memory_target(session_data)
        if do_protocol and session_data.get("target_kind") else None
    )
    do_protocol = bool(do_protocol and target)

    counters = state.read_window_state(owrap_sid, ccsid)
    cursor_ns = counters.get("transcript_cursor_ns", 0)

    now = time.time()
    since_last = now - counters.get("last_ctx_attempt_ts", 0)
    if since_last < CTX_MIN_INTERVAL_S:
        print(f"ctx-worker: {CTX_MIN_INTERVAL_S - since_last:.0f}s left", flush=True)
        return 0, None, None

    if transcript_lines is None:
        if not transcript_path or not Path(transcript_path).exists():
            print("ctx-worker: transcript path missing", file=sys.stderr)
            return 1, "transcript path missing", None
        transcript_lines = Path(transcript_path).read_text().splitlines()
    if cursor_ceiling_ns is not None:
        transcript_lines = lines_up_to_ceiling(transcript_lines, cursor_ceiling_ns)

    # Floor at this window's last attach — guards against a switched session.
    attach_ts_ns = last_attach_ts_ns(transcript_lines, owrap_sid)
    effective_cursor_ns = max(cursor_ns, attach_ts_ns)
    # Never move the cursor backward, even on an empty/malformed read.
    new_cursor_ns = max(
        latest_event_ns(transcript_lines) or 0, effective_cursor_ns,
    )
    event_ns = new_cursor_ns

    if source == "codex":
        new_assistant_texts = extract_codex_excerpt_lines(
            transcript_lines, effective_cursor_ns,
        )
    else:
        new_assistant_texts = extract_excerpt_lines(
            transcript_lines, effective_cursor_ns,
        )
    touched_entries = state.load_touched_entries(owrap_sid, ccsid)
    touched_lines = [
        f"[Touched] {e['path']}" + (f" — {e['note']}" if e.get("note") else "")
        for e in touched_entries
    ]
    repository_paths = {}
    if target:
        changed_paths = [entry["path"] for entry in touched_entries]
        for line in new_assistant_texts:
            match = re.match(r"\[(?:Edit|Write|NotebookEdit)\]\s+(\S+)", line)
            if match:
                changed_paths.append(match.group(1))
        repository_paths = touched_repository_paths(
            target, changed_paths, session_data.get("workspace", ""),
        )
        repository_paths.update(register_discovered_repositories(
            target, changed_paths, session_data.get("workspace", ""),
        ))
    combined_texts = new_assistant_texts + touched_lines

    if not combined_texts:
        print("ctx-worker: nothing to summarize", flush=True)
        # Leave a transcript.txt even when empty -- a missing one means a crash.
        placeholder = "(nothing new since the last update)"
        session_ctx_transcript_path(owrap_sid, ccsid).write_text(placeholder)
        if job_dir:
            (job_dir / "transcript.txt").write_text(placeholder)
        if has_recognized_transcript_entries(
            transcript_lines, effective_cursor_ns, source,
        ):
            counters["transcript_cursor_ns"] = new_cursor_ns
            state.write_window_state(owrap_sid, counters, ccsid)
        return 0, None, None

    excerpt = "\n\n".join(combined_texts)

    if len(excerpt) < CTX_MIN_CHARS:
        print(f"ctx-worker: need {CTX_MIN_CHARS - len(excerpt)} more chars", flush=True)
        # Cursor stays put so the next check sees the full accumulated excerpt.
        return 0, None, None

    excerpt_limit = (
        MAX_CODEX_EXCERPT_CHARS if source == "codex" else MAX_EXCERPT_CHARS
    )
    if len(excerpt) > excerpt_limit:
        dropped = len(excerpt) - excerpt_limit
        print(f"ctx-worker: excerpt truncated, dropped {dropped} chars")
        excerpt = excerpt[-excerpt_limit:]

    # Keep each model attempt isolated from other windows and jobs.
    ctx_dir = job_dir / "work" if job_dir else session_ctx_dir(owrap_sid, ccsid)
    ctx_dir.mkdir(parents=True, exist_ok=True)
    # A stray opencode.json here disqualifies OpenCode's free-tier models.
    (ctx_dir / "opencode.json").unlink(missing_ok=True)

    transcript_tmp = session_ctx_transcript_path(owrap_sid, ccsid)
    if job_dir:
        transcript_tmp = ctx_dir / "transcript.txt"
    transcript_tmp.write_text(excerpt)
    if job_dir:
        (job_dir / "transcript.txt").write_text(excerpt)
        context_jobs.update(job_dir, stage="building task")

    real_context_path = context_path(owrap_sid)
    projects_path = target.project_path if do_protocol else None

    # Model gets transcript only; our code merges its report deterministically.
    blocks = ""
    project_section = None
    if do_context:
        blocks += CTX_CONTEXT_BLOCK
    if do_protocol:
        if target.project_path:
            if target.subproject_id:
                record_kind = "Subproject"
                record_id = target.subproject_id
            else:
                record_kind = "Project"
                record_id = target.project_id
            project_section = f"{record_kind}: {record_id}"
            blocks += CTX_PROJECT_BLOCK.format(
                record_kind=record_kind,
                record_id=record_id,
            )
        for repo_id in repository_paths:
            blocks += CTX_REPOSITORY_BLOCK.format(repo_id=repo_id)
    if not blocks:
        counters["transcript_cursor_ns"] = new_cursor_ns
        state.write_window_state(owrap_sid, counters, ccsid)
        if touched_entries:
            state.clear_touched_entries(owrap_sid, ccsid)
        return 0, None, None
    task_content = CTX_SCOPED_TASK_TEMPLATE.format(blocks=blocks)
    if do_protocol:
        task_content += (
            "\nIf no project or repository fact is newer than this excerpt, "
            "omit its block. For an updr-only run with no updates, "
            "write exactly `# No updates`.\n"
        )

    (ctx_dir / "input.md").write_text(task_content)
    output_path = ctx_dir / "output.md"
    project_snapshot = (
        projects_path.read_bytes()
        if projects_path and projects_path.exists() else None
    )
    repository_snapshots = {
        repo_id: path.read_bytes() if path.exists() else None
        for repo_id, path in repository_paths.items()
    }

    print(
        f"ctx-worker: transcript since "
        f"{fmt_ts_ns(effective_cursor_ns)}..{fmt_ts_ns(new_cursor_ns)}",
        flush=True,
    )

    # Primary model retries once unless opencode is already known down.
    chain = get_model_chain(config)
    if read_opencode_status() == "down":
        attempts = [chain[0]] if chain else [None]
    else:
        # Empty chain (no config at all): one attempt, opencode's own default.
        attempts = [chain[0], chain[0]] + chain[1:] if chain else [None]
    rc = 1
    output_text = None
    attempt_metas = []
    model = None
    for model in attempts:
        if job_dir:
            context_jobs.update(
                job_dir, stage="running model", model=model or "default",
            )
        rc, candidate, meta = _run_dispatch_attempt(
            ctx_dir, output_path, model, len(excerpt),
        )
        attempt_metas.append(meta)
        if rc == 0 and candidate and validate_output(
            candidate, do_context, do_protocol,
        ):
            output_text = candidate
            break
        print(
            f"ctx-worker: attempt with model={model} produced no valid "
            "output, trying next",
            file=sys.stderr,
        )
        if len(attempt_metas) == 2 and all(
            m["idled_out"] and not strip_boilerplate(m["stdout"])
            for m in attempt_metas
        ):
            print(
                "ctx-worker: primary model gave no output twice in a "
                "row — treating as an infra failure, not retrying "
                "the rest of the chain",
                file=sys.stderr,
            )
            break

    if output_text is None:
        # No attempt produced usable output — down, whatever the rc.
        reason = _classify_opencode_failure(attempt_metas)
        _write_opencode_status("down", reason)
        print(
            "ctx-worker: all model attempts failed validation — "
            "leaving excerpt queued for the next dispatch",
            file=sys.stderr,
        )
        return 1, reason, None

    _write_opencode_status("up")
    if job_dir:
        (job_dir / "output.md").write_text(output_text)
        context_jobs.update(job_dir, stage="applying result")

    apply_record_output(
        output_text, real_context_path, projects_path,
        repository_paths, owrap_sid, project_snapshot, event_ns,
        repository_snapshots, project_section,
    )
    # Stamp only on success -- a failed attempt should retry as soon as
    # the next sweep tick, not wait out the same interval as a success.
    counters["last_ctx_attempt_ts"] = now
    counters["transcript_cursor_ns"] = new_cursor_ns
    state.write_window_state(owrap_sid, counters, ccsid)
    if touched_entries:
        state.clear_touched_entries(owrap_sid, ccsid)
    return rc, None, model


def _idle_timeout_factor(excerpt_len: int) -> float:
    """
    1x at CTX_MIN_CHARS, up to 3x at MAX_EXCERPT_CHARS, sqrt-ramped and
    clamped -- a bigger excerpt gives the model more to read before it
    produces any output, so the stuck-model detector needs more slack.
    """
    span = MAX_EXCERPT_CHARS - CTX_MIN_CHARS
    ratio = max(0.0, min(1.0, (excerpt_len - CTX_MIN_CHARS) / span))
    return 1 + 2 * math.sqrt(ratio)


def _run_dispatch_attempt(
    ctx_dir: Path, output_path: Path, model: str, excerpt_len: int,
) -> tuple:
    """
    Run one opencode dispatch attempt in `ctx_dir` with `model`.

    Returns (returncode, output_text_or_None, meta) — meta is
    {"idled_out": bool, "stdout": str, "model": str}, the detail a
    failed attempt needs for the opencode health flag's reason.
    """
    output_path.unlink(missing_ok=True)

    # pty below lets OpenCode auto-resolve/reject permissions on its own.
    cmd = ["opencode", "run", "--dir", str(ctx_dir)]
    if model:
        cmd.extend(["-m", model])
    cmd.extend([
        "--",
        # Plain English — --executor/--taskf needs AGENTS.md, unstaged here.
        "Read input.md in this directory and follow its instructions "
        f"exactly. {ANTI_SUMMARY_SUFFIX}",
    ])

    ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    print(
        f"ctx-worker: dispatching opencode model={model or '(opencode default)'} "
        f"(scoped dir, no pool) at {ts}",
        flush=True,
    )
    cmd_str = " ".join(shlex.quote(c) for c in cmd)
    terminal = Terminal(verbose=False)
    factor = _idle_timeout_factor(excerpt_len)
    # use_pty=True: without a real pty, OpenCode's permission prompt hangs.
    # idle_timeout: fail fast on a stuck model, scaled by excerpt size.
    result = terminal.run(
        cmd_str, capture_output=True, print_output=True,
        use_pty=True, cwd=str(ctx_dir), timeout=180,
        idle_timeout=round(CTX_IDLE_TIMEOUT_S * factor),
        idle_timeout_after=(
            CTX_READ_MARKER, round(CTX_IDLE_TIMEOUT_AFTER_READ_S * factor),
        ),
    )
    rc = result.get("returncode", 1)
    print(f"ctx-worker: opencode rc={rc}", flush=True)
    meta = {
        "idled_out": bool(result.get("idled_out")),
        "stdout": OutputParser().feed(result.get("stdout") or ""),
        "model": model or "(default)",
    }

    if not output_path.exists():
        print("ctx-worker: no output.md produced", file=sys.stderr)
        return rc, None, meta
    return rc, output_path.read_text(), meta


def _classify_opencode_failure(attempt_metas) -> str:
    """
    Describe why every dispatch attempt failed, for the shared
    opencode health flag's `reason` field (`owrap get opencode
    reason`): a model-specific plan restriction with its own error
    text, silence from every attempt, or an unclassified model
    error with a snippet of its last real output.
    """
    for meta in attempt_metas:
        if "subscription is required" in meta["stdout"]:
            line = meta["stdout"].strip().splitlines()[-1][:160]
            return f"subscription_required: {meta['model']} — {line}"
    # A partial response (idled out after some real progress) is a model_error.
    for meta in reversed(attempt_metas):
        stripped = strip_boilerplate(meta["stdout"])
        if stripped:
            line = stripped.splitlines()[-1][:160]
            suffix = " (idled out before finishing)" if meta["idled_out"] else ""
            return f"model_error: {meta['model']} — {line}{suffix}"
    if attempt_metas and all(m["idled_out"] for m in attempt_metas):
        models = ", ".join(dict.fromkeys(m["model"] for m in attempt_metas))
        return (
            f"no_output: {len(attempt_metas)} attempt(s) against "
            f"{models} gave no response"
        )
    return "model_error: no output from any attempt"


def hook_run() -> None:
    """
    Receive Claude/Codex's PreCompact hook data (on stdin) and spawn
    a background context-manager worker for the firing window
    (ccsid), if there's enough new content to justify one and the
    window's target isn't marked high-risk.
    """
    try:
        hook_data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        return

    config = _read_config()
    if not config.get("owrap_context_manager_enabled", True):
        return

    ccsid = hook_data.get("session_id", "")
    transcript_path = hook_data.get("transcript_path", "")

    owrap_sid = owrap_sid_for_ccsid(ccsid) if ccsid else None
    source = "claude"
    if not owrap_sid and ccsid:
        owrap_sid = owrap_sid_for_codex_session_id(ccsid)
        if owrap_sid:
            hook_data["source"] = "codex"
            source = "codex"

    if not owrap_sid:
        return
    if _is_high_risk_sid(owrap_sid):
        return

    # Same floor as every other caller -- skip outright rather than
    # spawn a subprocess _dispatch would immediately reject anyway.
    now = time.time()
    if _ctx_window_recently_attempted(owrap_sid, ccsid, now):
        return
    if not transcript_path or not Path(transcript_path).exists():
        return
    transcript_lines = Path(transcript_path).read_text().splitlines()
    if _pending_excerpt_len(owrap_sid, ccsid, transcript_lines, source) < CTX_MIN_CHARS:
        return

    ctx_dir = session_ctx_dir(owrap_sid, ccsid)
    ctx_dir.mkdir(parents=True, exist_ok=True)
    job_dir = context_jobs.create(owrap_sid, ccsid, "ctx+updr")
    hook_data["job_dir"] = str(job_dir)
    hook_data["cursor_ceiling_ns"] = latest_event_ns(transcript_lines)
    input_path = job_dir / "hook.json"
    input_path.write_text(json.dumps(hook_data))

    log_path = job_dir / "output.log"
    log_fd = open(str(log_path), "a")
    try:
        process = subprocess.Popen(
            [sys.executable, "-m", "owrap.kind.dispatch.ctx",
             "--input", str(input_path)],
            stdout=log_fd,
            stderr=log_fd,
            start_new_session=True,
            close_fds=True,
            cwd=str(Path(__file__).resolve().parents[2]),
        )
    except Exception:
        context_jobs.finish(job_dir, 1)
        raise
    finally:
        log_fd.close()
    if isinstance(process.pid, int):
        context_jobs.update(job_dir, pid=process.pid)
