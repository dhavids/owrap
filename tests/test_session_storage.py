from owrap.utils.session import resolver


def test_flat_session_storage_is_grouped(tmp_path, monkeypatch):
    sessions = tmp_path / "sessions"
    sessions.mkdir(exist_ok=True)
    (sessions / "abc123.session").write_text("session_id=abc123\n")
    (sessions / "abc123.codex-1.counters.json").write_text("{}")
    legacy_index = sessions / "by_codex_session_id"
    legacy_index.mkdir()
    (legacy_index / "codex-1").write_text("abc123")

    monkeypatch.setattr(resolver, "SESSIONS_DIR", sessions)
    monkeypatch.setattr(resolver, "SESSION_INDEX_DIR", sessions / "_index")
    monkeypatch.setattr(
        resolver, "BY_CCSID_DIR", sessions / "_index" / "claude",
    )
    monkeypatch.setattr(
        resolver, "BY_OPENCODE_RUN_ID_DIR", sessions / "_index" / "opencode",
    )
    monkeypatch.setattr(
        resolver, "BY_CODEX_SESSION_ID_DIR", sessions / "_index" / "codex",
    )

    moved = resolver.migrate_session_storage()

    assert moved == 3
    assert (sessions / "abc123" / ".session").is_file()
    assert (
        sessions / "abc123" / "ctx" / "windows" / "codex-1"
        / "counters.json"
    ).is_file()
    assert (sessions / "_index" / "codex" / "codex-1").is_file()
    assert not list(sessions.glob("*.session"))
    assert not list(sessions.glob("*.counters.json"))
