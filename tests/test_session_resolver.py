import os
from pathlib import Path
from unittest.mock import patch

import pytest

from owrap.utils.session_resolver import (
    SESSIONS_DIR,
    BY_CCSID_DIR,
    BY_OPENCODE_RUN_ID_DIR,
    ccsid_pointer,
    opencode_run_id_pointer,
    resolve,
    attach,
    remove_session,
    list_sessions,
)


class TestResolveOpencodeRunId:
    def test_resolve_finds_session_by_opencode_run_id(self, tmp_path, monkeypatch):
        monkeypatch.setattr("owrap.utils.session_resolver.SESSIONS_DIR", tmp_path)
        monkeypatch.setattr("owrap.utils.session_resolver.BY_CCSID_DIR", tmp_path / "by_ccsid")
        monkeypatch.setattr("owrap.utils.session_resolver.BY_OPENCODE_RUN_ID_DIR", tmp_path / "by_opencode_run_id")
        monkeypatch.setenv("OPENCODE_RUN_ID", "run-abc")
        monkeypatch.delenv("SESSION_ID", raising=False)
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)

        sf = tmp_path / "abc123.session"
        sf.write_text("session_id=abc123\n")
        opencode_run_id_pointer("run-abc").parent.mkdir(parents=True)
        opencode_run_id_pointer("run-abc").write_text("abc123")

        sid, sfile, source = resolve(mode="refresh")
        assert sid == "abc123"
        assert source == "opencode_run_id"

    def test_resolve_opencode_run_id_stale_pointer_removed(self, tmp_path, monkeypatch):
        monkeypatch.setattr("owrap.utils.session_resolver.SESSIONS_DIR", tmp_path)
        monkeypatch.setattr("owrap.utils.session_resolver.BY_CCSID_DIR", tmp_path / "by_ccsid")
        monkeypatch.setattr("owrap.utils.session_resolver.BY_OPENCODE_RUN_ID_DIR", tmp_path / "by_opencode_run_id")
        monkeypatch.setenv("OPENCODE_RUN_ID", "run-abc")
        monkeypatch.delenv("SESSION_ID", raising=False)
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)

        opencode_run_id_pointer("run-abc").parent.mkdir(parents=True)
        opencode_run_id_pointer("run-abc").write_text("missing")

        sid, sfile, source = resolve(mode="refresh")
        assert sid is None
        assert not opencode_run_id_pointer("run-abc").exists()

    def test_start_creates_opencode_run_id_pointer(self, tmp_path, monkeypatch):
        monkeypatch.setattr("owrap.utils.session_resolver.SESSIONS_DIR", tmp_path)
        monkeypatch.setattr("owrap.utils.session_resolver.BY_CCSID_DIR", tmp_path / "by_ccsid")
        monkeypatch.setattr("owrap.utils.session_resolver.BY_OPENCODE_RUN_ID_DIR", tmp_path / "by_opencode_run_id")
        monkeypatch.setenv("OPENCODE_RUN_ID", "run-xyz")
        monkeypatch.delenv("SESSION_ID", raising=False)
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)

        sid, sfile, source = resolve(mode="start")
        assert source == "minted"
        assert opencode_run_id_pointer("run-xyz").exists()
        assert opencode_run_id_pointer("run-xyz").read_text() == sid


class TestAttachSingleAnchor:
    def test_attach_ccsid_only(self, tmp_path, monkeypatch):
        monkeypatch.setattr("owrap.utils.session_resolver.SESSIONS_DIR", tmp_path)
        monkeypatch.setattr("owrap.utils.session_resolver.BY_CCSID_DIR", tmp_path / "by_ccsid")
        monkeypatch.setattr("owrap.utils.session_resolver.BY_OPENCODE_RUN_ID_DIR", tmp_path / "by_opencode_run_id")
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "ccsid-123")
        monkeypatch.delenv("OPENCODE_RUN_ID", raising=False)

        sf = tmp_path / "abc123.session"
        sf.write_text("session_id=abc123\n")

        sid, sfile, prev = attach("abc123")
        assert sid == "abc123"
        assert ccsid_pointer("ccsid-123").exists()
        assert ccsid_pointer("ccsid-123").read_text() == "abc123"
        d = _parse_session(sfile)
        assert d.get("claude_session_id") == "ccsid-123"
        assert d.get("opencode_run_id") == ""

    def test_attach_oid_only(self, tmp_path, monkeypatch):
        monkeypatch.setattr("owrap.utils.session_resolver.SESSIONS_DIR", tmp_path)
        monkeypatch.setattr("owrap.utils.session_resolver.BY_CCSID_DIR", tmp_path / "by_ccsid")
        monkeypatch.setattr("owrap.utils.session_resolver.BY_OPENCODE_RUN_ID_DIR", tmp_path / "by_opencode_run_id")
        monkeypatch.setenv("OPENCODE_RUN_ID", "run-xyz")
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)

        sf = tmp_path / "abc123.session"
        sf.write_text("session_id=abc123\n")

        sid, sfile, prev = attach("abc123")
        assert sid == "abc123"
        assert opencode_run_id_pointer("run-xyz").exists()
        assert opencode_run_id_pointer("run-xyz").read_text() == "abc123"
        d = _parse_session(sfile)
        assert d.get("opencode_run_id") == "run-xyz"
        assert d.get("claude_session_id") == ""

    def test_attach_both_ccsid_wins(self, tmp_path, monkeypatch):
        monkeypatch.setattr("owrap.utils.session_resolver.SESSIONS_DIR", tmp_path)
        monkeypatch.setattr("owrap.utils.session_resolver.BY_CCSID_DIR", tmp_path / "by_ccsid")
        monkeypatch.setattr("owrap.utils.session_resolver.BY_OPENCODE_RUN_ID_DIR", tmp_path / "by_opencode_run_id")
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "ccsid-123")
        monkeypatch.setenv("OPENCODE_RUN_ID", "run-xyz")

        sf = tmp_path / "abc123.session"
        sf.write_text("session_id=abc123\n")

        # Pre-existing oid pointer for this session
        opencode_run_id_pointer("run-xyz").parent.mkdir(parents=True)
        opencode_run_id_pointer("run-xyz").write_text("abc123")

        sid, sfile, prev = attach("abc123")
        assert sid == "abc123"
        assert ccsid_pointer("ccsid-123").exists()
        assert ccsid_pointer("ccsid-123").read_text() == "abc123"
        assert not opencode_run_id_pointer("run-xyz").exists()
        d = _parse_session(sfile)
        assert d.get("claude_session_id") == "ccsid-123"
        assert d.get("opencode_run_id") == ""

    def test_attach_neither_clears_both(self, tmp_path, monkeypatch):
        monkeypatch.setattr("owrap.utils.session_resolver.SESSIONS_DIR", tmp_path)
        monkeypatch.setattr("owrap.utils.session_resolver.BY_CCSID_DIR", tmp_path / "by_ccsid")
        monkeypatch.setattr("owrap.utils.session_resolver.BY_OPENCODE_RUN_ID_DIR", tmp_path / "by_opencode_run_id")
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        monkeypatch.delenv("OPENCODE_RUN_ID", raising=False)

        sf = tmp_path / "abc123.session"
        sf.write_text("session_id=abc123\nclaude_session_id=old-ccsid\nopencode_run_id=old-run\n")
        ccsid_pointer("old-ccsid").parent.mkdir(parents=True)
        ccsid_pointer("old-ccsid").write_text("abc123")
        opencode_run_id_pointer("old-run").parent.mkdir(parents=True)
        opencode_run_id_pointer("old-run").write_text("abc123")

        sid, sfile, prev = attach("abc123")
        assert sid == "abc123"
        assert not ccsid_pointer("old-ccsid").exists()
        assert not opencode_run_id_pointer("old-run").exists()
        d = _parse_session(sfile)
        assert d.get("claude_session_id") == ""
        assert d.get("opencode_run_id") == ""
        assert "attached_ppid" in d


class TestAttachOpencodeRunId:
    def test_attach_binds_opencode_run_id(self, tmp_path, monkeypatch):
        monkeypatch.setattr("owrap.utils.session_resolver.SESSIONS_DIR", tmp_path)
        monkeypatch.setattr("owrap.utils.session_resolver.BY_CCSID_DIR", tmp_path / "by_ccsid")
        monkeypatch.setattr("owrap.utils.session_resolver.BY_OPENCODE_RUN_ID_DIR", tmp_path / "by_opencode_run_id")
        monkeypatch.setenv("OPENCODE_RUN_ID", "run-abc")
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)

        sf = tmp_path / "abc123.session"
        sf.write_text("session_id=abc123\n")

        sid, sfile, prev = attach("abc123")
        assert sid == "abc123"
        assert opencode_run_id_pointer("run-abc").exists()
        assert opencode_run_id_pointer("run-abc").read_text() == "abc123"
        d = _parse_session(sfile)
        assert d.get("opencode_run_id") == "run-abc"

    def test_attach_rebinds_opencode_run_id_one_to_one(self, tmp_path, monkeypatch):
        monkeypatch.setattr("owrap.utils.session_resolver.SESSIONS_DIR", tmp_path)
        monkeypatch.setattr("owrap.utils.session_resolver.BY_CCSID_DIR", tmp_path / "by_ccsid")
        monkeypatch.setattr("owrap.utils.session_resolver.BY_OPENCODE_RUN_ID_DIR", tmp_path / "by_opencode_run_id")
        monkeypatch.setenv("OPENCODE_RUN_ID", "run-abc")
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)

        old_sf = tmp_path / "old.session"
        old_sf.write_text("session_id=old\nopencode_run_id=run-abc\n")
        new_sf = tmp_path / "new.session"
        new_sf.write_text("session_id=new\n")
        opencode_run_id_pointer("run-abc").parent.mkdir(parents=True)
        opencode_run_id_pointer("run-abc").write_text("old")

        sid, sfile, prev = attach("new")
        assert sid == "new"
        assert opencode_run_id_pointer("run-abc").read_text() == "new"
        old_d = _parse_session(old_sf)
        assert old_d.get("opencode_run_id") == ""


class TestRemoveSession:
    def test_remove_session_clears_opencode_run_id_pointer(self, tmp_path, monkeypatch):
        monkeypatch.setattr("owrap.utils.session_resolver.SESSIONS_DIR", tmp_path)
        monkeypatch.setattr("owrap.utils.session_resolver.BY_CCSID_DIR", tmp_path / "by_ccsid")
        monkeypatch.setattr("owrap.utils.session_resolver.BY_OPENCODE_RUN_ID_DIR", tmp_path / "by_opencode_run_id")

        sf = tmp_path / "abc123.session"
        sf.write_text("session_id=abc123\n")
        opencode_run_id_pointer("run-abc").parent.mkdir(parents=True)
        opencode_run_id_pointer("run-abc").write_text("abc123")

        remove_session("abc123")
        assert not sf.exists()
        assert not opencode_run_id_pointer("run-abc").exists()


class TestListSessions:
    def test_list_sessions_owned_by_opencode_run_id(self, tmp_path, monkeypatch):
        monkeypatch.setattr("owrap.utils.session_resolver.SESSIONS_DIR", tmp_path)
        monkeypatch.setattr("owrap.utils.session_resolver.BY_CCSID_DIR", tmp_path / "by_ccsid")
        monkeypatch.setattr("owrap.utils.session_resolver.BY_OPENCODE_RUN_ID_DIR", tmp_path / "by_opencode_run_id")
        monkeypatch.setenv("OPENCODE_RUN_ID", "run-abc")
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)

        sf = tmp_path / "abc123.session"
        sf.write_text("session_id=abc123\nopencode_run_id=run-abc\n")

        sessions = list_sessions()
        assert len(sessions) == 1
        assert sessions[0]["owned_by_current"] is True


def _parse_session(path: Path) -> dict:
    data = {}
    for line in path.read_text().splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            data[k.strip()] = v.strip()
    return data
