import pytest

from owrap.ctx import dispatch


def _setup(monkeypatch, tmp_path, high_risk):
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text("{}\n")
    session_path = tmp_path / "sid1.session"
    session_path.write_text("session_id=sid1\n")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "ccsid1")
    monkeypatch.delenv("CODEX_SESSION_ID", raising=False)
    monkeypatch.setattr(dispatch, "_read_config", lambda: {
        "owrap_context_manager_enabled": True,
    })
    monkeypatch.setattr(dispatch, "owrap_sid_for_ccsid", lambda ccsid: "sid1")
    monkeypatch.setattr(dispatch, "get_workspace_path", lambda: tmp_path)
    monkeypatch.setattr(
        dispatch, "claude_transcript_path", lambda ccsid, ws: transcript,
    )
    monkeypatch.setattr(dispatch, "session_file", lambda sid: session_path)
    monkeypatch.setattr(dispatch, "is_high_risk_session", lambda d: high_risk)
    return transcript


def test_run_manual_refuses_for_a_high_risk_session(monkeypatch, tmp_path, capsys):
    _setup(monkeypatch, tmp_path, high_risk=True)
    calls = []
    monkeypatch.setattr(
        dispatch.context_jobs, "create", lambda *a, **kw: calls.append(1),
    )

    with pytest.raises(SystemExit) as exc:
        dispatch.run_manual(mode="ctx")

    assert exc.value.code == 1
    assert "high-risk" in capsys.readouterr().out
    assert calls == []


def test_run_manual_proceeds_for_a_low_risk_session(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, high_risk=False)
    created = []
    monkeypatch.setattr(
        dispatch.context_jobs, "create",
        lambda *a, **kw: created.append(1) or tmp_path,
    )
    monkeypatch.setattr(dispatch, "session_ctx_dir", lambda *a: tmp_path)
    monkeypatch.setattr(
        dispatch.subprocess, "Popen",
        lambda *a, **kw: type("P", (), {"pid": 1})(),
    )
    monkeypatch.setattr(dispatch.context_jobs, "update", lambda *a, **kw: None)

    dispatch.run_manual(mode="ctx")

    assert created == [1]
