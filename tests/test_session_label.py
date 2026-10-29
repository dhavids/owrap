from owrap.utils.session import resolver


def _write_session(tmp_path, sid, **fields):
    path = tmp_path / sid / ".session"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{k}={v}" for k, v in fields.items()]
    path.write_text("\n".join(lines) + "\n")


def test_session_label_uses_project_id(monkeypatch, tmp_path):
    monkeypatch.setattr(resolver, "SESSIONS_DIR", tmp_path)
    _write_session(tmp_path, "sid1", project_id="owrap")
    assert resolver.session_label("sid1") == "owrap"


def test_session_label_qualifies_with_subproject(monkeypatch, tmp_path):
    monkeypatch.setattr(resolver, "SESSIONS_DIR", tmp_path)
    _write_session(tmp_path, "sid1", project_id="owrap", subproject_id="docs")
    assert resolver.session_label("sid1") == "owrap/docs"


def test_session_label_falls_back_to_session_id_without_a_project(
    monkeypatch, tmp_path,
):
    monkeypatch.setattr(resolver, "SESSIONS_DIR", tmp_path)
    _write_session(tmp_path, "sid1", repository_id="some-repo")
    assert resolver.session_label("sid1") == "sid1"


def test_session_label_falls_back_to_session_id_when_file_missing(
    monkeypatch, tmp_path,
):
    monkeypatch.setattr(resolver, "SESSIONS_DIR", tmp_path)
    assert resolver.session_label("no-such-session") == "no-such-session"
