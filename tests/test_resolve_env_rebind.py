from owrap.session import resolver


def _session(tmp_path, sid):
    path = tmp_path / f"{sid}.session"
    path.write_text(f"session_id={sid}\n")
    return path


def _patch_dirs(monkeypatch, tmp_path):
    monkeypatch.setattr(resolver, "SESSIONS_DIR", tmp_path)
    monkeypatch.setattr(resolver, "BY_CCSID_DIR", tmp_path / "by_ccsid")
    monkeypatch.setattr(
        resolver, "BY_CODEX_SESSION_ID_DIR", tmp_path / "by_codex",
    )
    monkeypatch.setattr(
        resolver, "BY_OPENCODE_RUN_ID_DIR", tmp_path / "by_opencode",
    )
    monkeypatch.setattr(resolver, "session_file", lambda sid: tmp_path / f"{sid}.session")


def test_env_resolve_binds_a_ccsid_with_no_existing_pointer(monkeypatch, tmp_path):
    _patch_dirs(monkeypatch, tmp_path)
    _session(tmp_path, "abc123")
    monkeypatch.setenv("SESSION_ID", "abc123")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "new-ccsid")
    monkeypatch.delenv("CODEX_SESSION_ID", raising=False)

    sid, _, source = resolver.resolve(mode="refresh")

    assert (sid, source) == ("abc123", "env")
    assert resolver.ccsid_pointer("new-ccsid").read_text().strip() == "abc123"


def test_env_resolve_rebinds_a_ccsid_pointing_at_a_different_session(
    monkeypatch, tmp_path,
):
    """
    A harness restart can mint a new ccsid while SESSION_ID stays set;
    an unrelated session's stale ccsid pointer must not be mistaken
    for this one still being correctly bound.
    """
    _patch_dirs(monkeypatch, tmp_path)
    _session(tmp_path, "abc123")
    resolver.ccsid_pointer("old-ccsid").parent.mkdir(parents=True, exist_ok=True)
    resolver.ccsid_pointer("old-ccsid").write_text("some-other-session")
    monkeypatch.setenv("SESSION_ID", "abc123")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "old-ccsid")
    monkeypatch.delenv("CODEX_SESSION_ID", raising=False)

    sid, _, source = resolver.resolve(mode="refresh")

    assert (sid, source) == ("abc123", "env")
    assert resolver.ccsid_pointer("old-ccsid").read_text().strip() == "abc123"


def test_env_resolve_leaves_an_already_correct_ccsid_pointer_untouched(
    monkeypatch, tmp_path,
):
    _patch_dirs(monkeypatch, tmp_path)
    _session(tmp_path, "abc123")
    resolver.ccsid_pointer("ccsid1").parent.mkdir(parents=True, exist_ok=True)
    resolver.ccsid_pointer("ccsid1").write_text("abc123")
    before = resolver.ccsid_pointer("ccsid1").stat().st_mtime
    monkeypatch.setenv("SESSION_ID", "abc123")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "ccsid1")
    monkeypatch.delenv("CODEX_SESSION_ID", raising=False)

    resolver.resolve(mode="refresh")

    assert resolver.ccsid_pointer("ccsid1").stat().st_mtime == before


def test_env_resolve_also_rebinds_a_stale_codex_session_id(monkeypatch, tmp_path):
    _patch_dirs(monkeypatch, tmp_path)
    _session(tmp_path, "abc123")
    monkeypatch.setenv("SESSION_ID", "abc123")
    monkeypatch.setenv("CODEX_SESSION_ID", "new-cid")
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)

    sid, _, source = resolver.resolve(mode="refresh")

    assert (sid, source) == ("abc123", "env")
    assert resolver.codex_session_id_pointer("new-cid").read_text().strip() == "abc123"
