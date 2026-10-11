import io
import json

from owrap.ctx import dispatch


def _stdin(payload):
    return io.StringIO(json.dumps(payload))


def test_hook_run_skips_a_high_risk_session_without_spawning_a_worker(
    monkeypatch,
):
    monkeypatch.setattr(
        dispatch.sys, "stdin",
        _stdin({"session_id": "ccsid1", "transcript_path": "transcript.txt"}),
    )
    monkeypatch.setattr(dispatch, "_read_config", lambda: {
        "owrap_context_manager_enabled": True,
    })
    monkeypatch.setattr(dispatch, "owrap_sid_for_ccsid", lambda ccsid: "sid1")
    monkeypatch.setattr(dispatch, "_is_high_risk_sid", lambda sid: True)
    calls = []
    monkeypatch.setattr(
        dispatch.context_jobs, "create", lambda *a, **kw: calls.append(1),
    )
    monkeypatch.setattr(
        dispatch.subprocess, "Popen", lambda *a, **kw: calls.append(1),
    )

    dispatch.hook_run()

    assert calls == []


def test_hook_run_proceeds_for_a_low_risk_session(monkeypatch, tmp_path):
    transcript = tmp_path / "transcript.txt"
    transcript.write_text("{}\n")
    monkeypatch.setattr(
        dispatch.sys, "stdin",
        _stdin({"session_id": "ccsid1", "transcript_path": str(transcript)}),
    )
    monkeypatch.setattr(dispatch, "_read_config", lambda: {
        "owrap_context_manager_enabled": True,
    })
    monkeypatch.setattr(dispatch, "owrap_sid_for_ccsid", lambda ccsid: "sid1")
    monkeypatch.setattr(dispatch, "_is_high_risk_sid", lambda sid: False)
    monkeypatch.setattr(dispatch, "_ctx_window_recently_attempted", lambda *a: False)
    monkeypatch.setattr(
        dispatch, "_pending_excerpt_len", lambda *a: dispatch.CTX_MIN_CHARS,
    )
    monkeypatch.setattr(dispatch, "session_ctx_dir", lambda *a: tmp_path)
    created = []
    monkeypatch.setattr(
        dispatch.context_jobs, "create",
        lambda *a, **kw: created.append(1) or tmp_path,
    )
    monkeypatch.setattr(
        dispatch.subprocess, "Popen",
        lambda *a, **kw: type("P", (), {"pid": 1})(),
    )
    monkeypatch.setattr(dispatch.context_jobs, "update", lambda *a, **kw: None)

    dispatch.hook_run()

    assert created == [1]
