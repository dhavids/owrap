import json

import pytest


def _patch_dirs(monkeypatch, tmp_path):
    sessions_dir = tmp_path / "sessions"
    monkeypatch.setattr("owrap.utils.paths.SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr("owrap.utils.session.session_resolver.SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(
        "owrap.utils.session.session_resolver.BY_CCSID_DIR", sessions_dir / "by_ccsid",
    )
    return sessions_dir


def _attach(sessions_dir, ccsid, owrap_sid):
    by_ccsid = sessions_dir / "by_ccsid"
    by_ccsid.mkdir(parents=True, exist_ok=True)
    (by_ccsid / ccsid).write_text(owrap_sid)


def test_touched_errors_without_ccsid(monkeypatch, tmp_path):
    from owrap.commands.touched_cmd import TouchedRunner
    _patch_dirs(monkeypatch, tmp_path)
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)

    with pytest.raises(SystemExit) as exc_info:
        TouchedRunner().run(["owrap/foo.py"])
    assert exc_info.value.code == 1


def test_touched_errors_without_attached_session(monkeypatch, tmp_path):
    from owrap.commands.touched_cmd import TouchedRunner
    _patch_dirs(monkeypatch, tmp_path)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "claude-1")

    with pytest.raises(SystemExit) as exc_info:
        TouchedRunner().run(["owrap/foo.py"])
    assert exc_info.value.code == 1


def test_touched_writes_entries(monkeypatch, tmp_path):
    from owrap.commands.touched_cmd import TouchedRunner
    from owrap.utils.paths import session_ctx_touched_path
    sessions_dir = _patch_dirs(monkeypatch, tmp_path)
    _attach(sessions_dir, "claude-1", "sid01")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "claude-1")

    TouchedRunner().run(["owrap/foo.py", "owrap/bar.py"], note="renamed helper")

    entries = json.loads(session_ctx_touched_path("sid01", "claude-1").read_text())
    assert entries == [
        {"path": "owrap/foo.py", "note": "renamed helper"},
        {"path": "owrap/bar.py", "note": "renamed helper"},
    ]


def test_touched_appends_to_existing_entries(monkeypatch, tmp_path):
    from owrap.commands.touched_cmd import TouchedRunner
    from owrap.utils.paths import session_ctx_touched_path
    sessions_dir = _patch_dirs(monkeypatch, tmp_path)
    _attach(sessions_dir, "claude-1", "sid01")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "claude-1")

    TouchedRunner().run(["owrap/foo.py"], note="first")
    TouchedRunner().run(["owrap/bar.py"], note="second")

    entries = json.loads(session_ctx_touched_path("sid01", "claude-1").read_text())
    assert entries == [
        {"path": "owrap/foo.py", "note": "first"},
        {"path": "owrap/bar.py", "note": "second"},
    ]
