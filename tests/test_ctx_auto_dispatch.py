"""
`check_all_attached()`'s job-tracking wrapper (owrap/ctx/dispatch.py's
`_dispatch_and_track`) -- the daemon's own background ctx/updr checks
used to call `_dispatch_tracked` with no job at all, so an automatic
dispatch never showed up in `context_jobs`/rtlog/`owrap stat`, only
manual `--ctx`/`--uall` calls did. Reading the code doesn't confirm
the fix actually produces a `context_jobs` record end to end -- that
requires running it and inspecting what `context_jobs.recent()` sees.
"""
import pytest

from owrap.ctx import dispatch
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
