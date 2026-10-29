"""
`check_all_attached()`'s job-tracking, gating, and backoff behavior --
confirming a dispatch actually produces a `context_jobs`/rtlog record,
and that the gates actually hold, needs a real run, not a code read.
"""
import json
import time
from pathlib import Path

from owrap.ctx import dispatch
from owrap.ctx.excerpt import ts_ns
from owrap.utils.log import context_jobs


def _attached_window(monkeypatch, tmp_path, transcript_name="transcript.jsonl"):
    transcript = tmp_path / transcript_name
    transcript.write_text("{}\n")
    monkeypatch.setattr(dispatch, "_read_config", lambda: {
        "owrap_context_manager_enabled": True,
    })
    monkeypatch.setattr(dispatch, "get_workspace_path", lambda: tmp_path)
    monkeypatch.setattr(dispatch, "claude_transcript_path", lambda ccsid, ws: transcript)
    monkeypatch.setattr(dispatch, "codex_transcript_path", lambda cid: None)
    # These tests exercise job-tracking, not the size gate -- keep it open.
    monkeypatch.setattr(
        dispatch, "_pending_excerpt_len", lambda *a: dispatch.CTX_MIN_CHARS,
    )
    return transcript


def test_check_all_attached_creates_and_finishes_a_job(monkeypatch, tmp_path):
    _attached_window(monkeypatch, tmp_path)
    monkeypatch.setattr(
        dispatch, "all_attached_ccsid_pairs", lambda: [("ccsid1", "sid1")],
    )
    monkeypatch.setattr(dispatch, "all_attached_codex_session_id_pairs", lambda: [])

    seen = {}

    def fake_dispatch_tracked(owrap_sid, ccsid, transcript_path, config, **kwargs):
        seen["owrap_sid"] = owrap_sid
        seen["ccsid"] = ccsid
        seen["job_dir"] = kwargs.get("job_dir")
        return 0

    monkeypatch.setattr(dispatch, "_dispatch_tracked", fake_dispatch_tracked)

    dispatch.check_all_attached()

    assert seen["owrap_sid"] == "sid1"
    assert seen["ccsid"] == "ccsid1"
    assert seen["job_dir"] is not None

    jobs = context_jobs.recent("sid1")
    assert len(jobs) == 1
    assert jobs[0]["status"] == "succeeded"
    assert jobs[0]["rc"] == 0
    assert jobs[0]["kind"] == "auto"


def test_check_all_attached_captures_its_own_prints_into_the_job_log(
    monkeypatch, tmp_path,
):
    """
    The background path runs in-process, so its prints only land in
    the job's own log; `_dispatch_and_track` explicitly
    redirects sys.stdout there for the duration of the dispatch.
    """
    _attached_window(monkeypatch, tmp_path)
    monkeypatch.setattr(
        dispatch, "all_attached_ccsid_pairs", lambda: [("ccsid1", "sid1")],
    )
    monkeypatch.setattr(dispatch, "all_attached_codex_session_id_pairs", lambda: [])

    def fake_dispatch_tracked(*a, **kwargs):
        print("marker line from a background dispatch")
        return 0

    monkeypatch.setattr(dispatch, "_dispatch_tracked", fake_dispatch_tracked)

    dispatch.check_all_attached()

    jobs = context_jobs.recent("sid1")
    log_path = Path(jobs[0]["log_path"])
    assert "marker line from a background dispatch" in log_path.read_text()


def test_check_all_attached_still_finishes_job_when_dispatch_raises(
    monkeypatch, tmp_path,
):
    _attached_window(monkeypatch, tmp_path)
    monkeypatch.setattr(
        dispatch, "all_attached_ccsid_pairs", lambda: [("ccsid2", "sid2")],
    )
    monkeypatch.setattr(dispatch, "all_attached_codex_session_id_pairs", lambda: [])

    def raising_dispatch_tracked(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(dispatch, "_dispatch_tracked", raising_dispatch_tracked)

    # check_all_attached never raises -- one window's failure is
    # logged and skipped, not propagated.
    dispatch.check_all_attached()

    jobs = context_jobs.recent("sid2")
    assert len(jobs) == 1
    assert jobs[0]["status"] == "failed"
    assert jobs[0]["rc"] == 1


def test_check_all_attached_tracks_codex_windows_too(monkeypatch, tmp_path):
    transcript = tmp_path / "codex_transcript.jsonl"
    transcript.write_text("{}\n")
    monkeypatch.setattr(dispatch, "_read_config", lambda: {
        "owrap_context_manager_enabled": True,
    })
    monkeypatch.setattr(dispatch, "get_workspace_path", lambda: tmp_path)
    monkeypatch.setattr(dispatch, "all_attached_ccsid_pairs", lambda: [])
    monkeypatch.setattr(
        dispatch, "all_attached_codex_session_id_pairs", lambda: [("cid1", "sid3")],
    )
    monkeypatch.setattr(dispatch, "codex_transcript_path", lambda cid: transcript)
    monkeypatch.setattr(
        dispatch, "_pending_excerpt_len", lambda *a: dispatch.CTX_MIN_CHARS,
    )

    seen = {}

    def fake_dispatch_tracked(owrap_sid, ccsid, transcript_path, config, **kwargs):
        seen["source"] = kwargs.get("source")
        return 0

    monkeypatch.setattr(dispatch, "_dispatch_tracked", fake_dispatch_tracked)

    dispatch.check_all_attached()

    assert seen["source"] == "codex"
    jobs = context_jobs.recent("sid3")
    assert len(jobs) == 1
    assert jobs[0]["status"] == "succeeded"


def test_check_all_attached_noop_when_context_manager_disabled(monkeypatch):
    monkeypatch.setattr(dispatch, "_read_config", lambda: {
        "owrap_context_manager_enabled": False,
    })
    calls = []
    monkeypatch.setattr(
        dispatch, "all_attached_ccsid_pairs", lambda: calls.append(1) or [],
    )
    dispatch.check_all_attached()
    assert calls == []


def test_check_all_attached_logs_a_summary_even_with_no_windows(monkeypatch, tmp_path):
    """
    A tick with nothing to do must still leave a trace in rtlog, even
    when every window is skipped or none are attached at all.
    """
    monkeypatch.setattr(dispatch, "AUTO_CTX_STATE_FILE", tmp_path / "backoff.json")
    monkeypatch.setattr(dispatch, "_read_config", lambda: {
        "owrap_context_manager_enabled": True,
    })
    monkeypatch.setattr(dispatch, "all_attached_ccsid_pairs", lambda: [])
    monkeypatch.setattr(dispatch, "all_attached_codex_session_id_pairs", lambda: [])
    logged = []
    monkeypatch.setattr(
        dispatch.rtlog, "log", lambda event, **fields: logged.append((event, fields)),
    )

    dispatch.check_all_attached()

    assert logged == [("ctx.check", {"backoff": False, "windows": 0,
                                      "dispatched": 0, "cooldown": 0, "too_small": 0})]


def test_check_all_attached_logs_backoff_without_checking_any_window(
    monkeypatch, tmp_path,
):
    monkeypatch.setattr(dispatch, "AUTO_CTX_STATE_FILE", tmp_path / "backoff.json")
    monkeypatch.setattr(dispatch, "_read_config", lambda: {
        "owrap_context_manager_enabled": True,
    })
    now = time.time()
    for _ in range(3):
        dispatch._record_auto_ctx_outcome(success=False, now=now)
    calls = []
    monkeypatch.setattr(
        dispatch, "all_attached_ccsid_pairs", lambda: calls.append(1) or [],
    )
    logged = []
    monkeypatch.setattr(
        dispatch.rtlog, "log", lambda event, **fields: logged.append((event, fields)),
    )

    dispatch.check_all_attached()

    assert calls == []
    assert logged == [("ctx.check", {"backoff": True})]


def test_check_all_attached_skips_job_creation_for_a_recently_attempted_window(
    monkeypatch, tmp_path,
):
    """
    `check_all_attached`'s pre-check must not even create a job for a
    window `_dispatch` already attempted inside CTX_MIN_INTERVAL_S --
    `_dispatch` itself is the one that persists the timestamp (it's
    the authoritative gate; this is purely a job-creation optimization),
    so this is read-only state that a code read alone can't confirm
    actually suppresses the call.
    """
    _attached_window(monkeypatch, tmp_path)
    monkeypatch.setattr(
        dispatch, "all_attached_ccsid_pairs", lambda: [("ccsid1", "sid1")],
    )
    monkeypatch.setattr(dispatch, "all_attached_codex_session_id_pairs", lambda: [])
    monkeypatch.setattr(
        dispatch.state, "read_window_state",
        lambda *a: {"last_ctx_attempt_ts": time.time()},
    )
    calls = []
    monkeypatch.setattr(
        dispatch, "_dispatch_tracked",
        lambda *a, **kw: calls.append(1) or 0,
    )

    dispatch.check_all_attached()

    assert calls == []


def test_check_all_attached_never_queues_a_job_for_too_small_an_excerpt(
    monkeypatch, tmp_path,
):
    """
    A window with "nothing to summarize" must not even reach
    _dispatch_and_track -- no job directory, no ctx.queued/done pair,
    not just a trivial one. Confirmed by watching both the dispatch
    call and the ctx.check summary's too_small count, not a code read.
    """
    _attached_window(monkeypatch, tmp_path)
    monkeypatch.setattr(
        dispatch, "all_attached_ccsid_pairs", lambda: [("ccsid1", "sid1")],
    )
    monkeypatch.setattr(dispatch, "all_attached_codex_session_id_pairs", lambda: [])
    monkeypatch.setattr(dispatch, "_pending_excerpt_len", lambda *a: 0)
    calls = []
    monkeypatch.setattr(
        dispatch, "_dispatch_tracked", lambda *a, **kw: calls.append(1) or 0,
    )
    logged = []
    monkeypatch.setattr(
        dispatch.rtlog, "log", lambda event, **fields: logged.append((event, fields)),
    )

    dispatch.check_all_attached()

    assert calls == []
    assert logged[-1] == (
        "ctx.check",
        {"backoff": False, "windows": 1, "dispatched": 0, "cooldown": 0, "too_small": 1},
    )


def test_check_all_attached_excludes_a_high_risk_window_entirely(
    monkeypatch, tmp_path,
):
    """
    A high-risk window must not be counted at all, not even as a
    too-small/cooldown skip -- it never reaches the per-window body.
    """
    _attached_window(monkeypatch, tmp_path)
    monkeypatch.setattr(
        dispatch, "all_attached_ccsid_pairs", lambda: [("ccsid1", "sid1")],
    )
    monkeypatch.setattr(dispatch, "all_attached_codex_session_id_pairs", lambda: [])
    monkeypatch.setattr(dispatch, "_is_high_risk_sid", lambda sid: True)
    calls = []
    monkeypatch.setattr(
        dispatch, "_dispatch_tracked", lambda *a, **kw: calls.append(1) or 0,
    )
    logged = []
    monkeypatch.setattr(
        dispatch.rtlog, "log", lambda event, **fields: logged.append((event, fields)),
    )

    dispatch.check_all_attached()

    assert calls == []
    assert logged[-1] == (
        "ctx.check",
        {"backoff": False, "windows": 0, "dispatched": 0, "cooldown": 0, "too_small": 0},
    )


def test_auto_ctx_due_respects_base_15m_cadence_before_three_failures(
    monkeypatch, tmp_path,
):
    monkeypatch.setattr(dispatch, "AUTO_CTX_STATE_FILE", tmp_path / "backoff.json")
    now = 1_000_000.0
    assert dispatch._auto_ctx_due(now) is True
    dispatch._record_auto_ctx_outcome(success=False, now=now)
    dispatch._record_auto_ctx_outcome(success=False, now=now)
    assert dispatch._auto_ctx_due(now + 1) is False
    assert dispatch._auto_ctx_due(now + 900) is True


def test_auto_ctx_backoff_schedule_advances_per_failure_then_cycles(
    monkeypatch, tmp_path,
):
    """
    3 consecutive background failures hold off the next try for 15m;
    a 4th failure (once that 15m clears) pushes it to 1h, then 2h,
    then a further failure cycles back to 15m.
    """
    monkeypatch.setattr(dispatch, "AUTO_CTX_STATE_FILE", tmp_path / "backoff.json")
    now = 1_000_000.0
    for _ in range(3):
        dispatch._record_auto_ctx_outcome(success=False, now=now)
    assert dispatch._auto_ctx_due(now + 1) is False
    assert dispatch._auto_ctx_due(now + 900) is True

    dispatch._record_auto_ctx_outcome(success=False, now=now + 900)
    assert dispatch._auto_ctx_due(now + 900 + 1) is False
    assert dispatch._auto_ctx_due(now + 900 + 3600) is True

    dispatch._record_auto_ctx_outcome(success=False, now=now + 900 + 3600)
    assert dispatch._auto_ctx_due(now + 900 + 3600 + 7199) is False
    assert dispatch._auto_ctx_due(now + 900 + 3600 + 7200) is True

    # Cycles back to 15m after 2h, rather than capping or climbing further.
    dispatch._record_auto_ctx_outcome(
        success=False, now=now + 900 + 3600 + 7200,
    )
    assert dispatch._auto_ctx_due(now + 900 + 3600 + 7200 + 899) is False
    assert dispatch._auto_ctx_due(now + 900 + 3600 + 7200 + 900) is True


def test_auto_ctx_backoff_resets_on_any_success(monkeypatch, tmp_path):
    monkeypatch.setattr(dispatch, "AUTO_CTX_STATE_FILE", tmp_path / "backoff.json")
    now = 1_000_000.0
    for _ in range(3):
        dispatch._record_auto_ctx_outcome(success=False, now=now)
    assert dispatch._auto_ctx_due(now + 1) is False

    dispatch._record_auto_ctx_outcome(success=True, now=now + 1)

    # Back to the base 15m cadence, not the 1h+ backoff interval.
    assert dispatch._auto_ctx_due(now + 1 + 899) is False
    assert dispatch._auto_ctx_due(now + 1 + 900) is True


def test_dispatch_tracked_records_auto_failure_but_not_manual_failure(
    monkeypatch, tmp_path,
):
    """
    `_dispatch_tracked` is the one choke point shared by the
    background, manual, and PreCompact paths -- only a background
    (is_auto=True) failure should count against the backoff schedule;
    a manual/PreCompact failure shouldn't silently poison it.
    """
    monkeypatch.setattr(dispatch, "AUTO_CTX_STATE_FILE", tmp_path / "backoff.json")
    monkeypatch.setattr(dispatch.state, "set_ctx_dispatch_result", lambda *a, **kw: None)
    monkeypatch.setattr(
        dispatch, "_dispatch",
        lambda *a, **kw: (1, "opencode down", None),
    )

    dispatch._dispatch_tracked(
        "sid", "ccsid", "path", {}, do_context=True, do_protocol=True,
        is_auto=False,
    )
    assert dispatch._read_auto_ctx_backoff()["consecutive_fails"] == 0

    dispatch._dispatch_tracked(
        "sid", "ccsid", "path", {}, do_context=True, do_protocol=True,
        is_auto=True,
    )
    assert dispatch._read_auto_ctx_backoff()["consecutive_fails"] == 1


def test_dispatch_skips_model_call_when_excerpt_too_small(monkeypatch, tmp_path):
    """
    An excerpt under CTX_MIN_CHARS must never reach the model (or
    advance the cursor), for any caller -- background, manual, or
    PreCompact alike -- confirmed by watching `_run_dispatch_attempt`/
    `_write_opencode_status`, not by reading the gate in isolation.
    """
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text("{}\n")
    attempts = []
    monkeypatch.setattr(dispatch, "session_file", lambda sid: tmp_path / "missing")
    monkeypatch.setattr(dispatch.state, "read_window_state", lambda *a: {})
    monkeypatch.setattr(dispatch.state, "load_touched_entries", lambda *a: [])
    write_calls = []
    monkeypatch.setattr(
        dispatch.state, "write_window_state",
        lambda *a, **kw: write_calls.append(1),
    )
    monkeypatch.setattr(dispatch, "last_attach_ts_ns", lambda *a: 0)
    monkeypatch.setattr(dispatch, "latest_event_ns", lambda *a: 1000)
    monkeypatch.setattr(dispatch, "extract_excerpt_lines", lambda *a: ["short"])
    monkeypatch.setattr(
        dispatch, "_run_dispatch_attempt",
        lambda *a, **kw: attempts.append(1),
    )
    monkeypatch.setattr(dispatch, "_write_opencode_status", lambda *a, **kw: None)

    rc, reason, model = dispatch._dispatch(
        "sid", "ccsid", str(transcript), {}, do_context=True, do_protocol=False,
    )

    assert (rc, reason, model) == (0, None, None)
    assert attempts == []
    assert write_calls == []


def test_dispatch_skips_model_call_when_too_soon_since_last_attempt(
    monkeypatch, tmp_path,
):
    """
    A window inside CTX_MIN_INTERVAL_S of its own last real attempt
    must be skipped before the excerpt is even read, for any caller --
    manual/PreCompact get no exemption from this either.
    """
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text("{}\n")
    monkeypatch.setattr(dispatch, "session_file", lambda sid: tmp_path / "missing")
    monkeypatch.setattr(
        dispatch.state, "read_window_state",
        lambda *a: {"last_ctx_attempt_ts": time.time()},
    )
    attempts = []
    monkeypatch.setattr(
        dispatch, "extract_excerpt_lines",
        lambda *a: attempts.append(1) or ["long enough text"],
    )

    rc, reason, model = dispatch._dispatch(
        "sid", "ccsid", str(transcript), {}, do_context=True, do_protocol=False,
    )

    assert (rc, reason, model) == (0, None, None)
    assert attempts == []


def test_dispatch_reaches_model_once_both_gates_clear(monkeypatch, tmp_path):
    """
    An excerpt at/above CTX_MIN_CHARS, with no recent attempt on
    record, does reach the model -- the gate blocks small/frequent
    attempts, it doesn't block dispatch outright.
    """
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text("{}\n")
    monkeypatch.setattr(dispatch, "session_file", lambda sid: tmp_path / "missing")
    monkeypatch.setattr(dispatch.state, "read_window_state", lambda *a: {})
    monkeypatch.setattr(dispatch.state, "load_touched_entries", lambda *a: [])
    monkeypatch.setattr(dispatch.state, "write_window_state", lambda *a, **kw: None)
    monkeypatch.setattr(dispatch.state, "clear_touched_entries", lambda *a: None)
    monkeypatch.setattr(dispatch, "last_attach_ts_ns", lambda *a: 0)
    monkeypatch.setattr(dispatch, "latest_event_ns", lambda *a: 1000)
    long_text = "x" * dispatch.CTX_MIN_CHARS
    monkeypatch.setattr(dispatch, "extract_excerpt_lines", lambda *a: [long_text])
    monkeypatch.setattr(dispatch, "get_model_chain", lambda *a, **kw: ["m1"])
    monkeypatch.setattr(dispatch, "read_opencode_status", lambda: "up")
    monkeypatch.setattr(
        dispatch, "_run_dispatch_attempt",
        lambda *a, **kw: (0, "output", {"idled_out": False, "stdout": "output"}),
    )
    monkeypatch.setattr(dispatch, "validate_output", lambda *a, **kw: True)
    monkeypatch.setattr(dispatch, "apply_record_output", lambda *a, **kw: None)
    statuses = []
    monkeypatch.setattr(
        dispatch, "_write_opencode_status", lambda *a, **kw: statuses.append(a),
    )

    rc, reason, model = dispatch._dispatch(
        "sid", "ccsid", str(transcript), {}, do_context=True, do_protocol=False,
    )

    assert (rc, reason, model) == (0, None, "m1")
    assert statuses == [("up",)]


def test_pending_excerpt_len_counts_only_lines_after_the_cursor(monkeypatch):
    old_line = json.dumps({
        "type": "assistant", "timestamp": "2026-01-01T00:00:00Z",
        "message": {"content": [{"type": "text", "text": "old, before cursor"}]},
    })
    new_line = json.dumps({
        "type": "assistant", "timestamp": "2026-01-02T00:00:00Z",
        "message": {"content": [{"type": "text", "text": "new, after cursor"}]},
    })
    monkeypatch.setattr(
        dispatch.state, "read_window_state",
        lambda *a: {"transcript_cursor_ns": ts_ns("2026-01-01T12:00:00Z")},
    )
    monkeypatch.setattr(dispatch.state, "load_touched_entries", lambda *a: [])

    pending = dispatch._pending_excerpt_len(
        "sid", "ccsid", [old_line, new_line], "claude",
    )

    assert pending == len("new, after cursor")


def test_pending_excerpt_len_zero_with_no_new_content(monkeypatch):
    old_line = json.dumps({
        "type": "assistant", "timestamp": "2026-01-01T00:00:00Z",
        "message": {"content": [{"type": "text", "text": "old"}]},
    })
    monkeypatch.setattr(
        dispatch.state, "read_window_state",
        lambda *a: {"transcript_cursor_ns": ts_ns("2026-01-02T00:00:00Z")},
    )
    monkeypatch.setattr(dispatch.state, "load_touched_entries", lambda *a: [])

    assert dispatch._pending_excerpt_len("sid", "ccsid", [old_line], "claude") == 0
