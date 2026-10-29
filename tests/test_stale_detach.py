import os
import time

from owrap.ctx import dispatch
from owrap.utils.session import resolver


def _patch_dirs(monkeypatch, tmp_path):
    monkeypatch.setattr(resolver, "SESSIONS_DIR", tmp_path)
    monkeypatch.setattr(resolver, "BY_CCSID_DIR", tmp_path / "by_ccsid")
    monkeypatch.setattr(resolver, "BY_CODEX_SESSION_ID_DIR", tmp_path / "by_codex")
    monkeypatch.setattr(resolver, "session_file", lambda sid: tmp_path / f"{sid}.session")


def test_detach_window_removes_claude_pointer_and_clears_session_field(
    monkeypatch, tmp_path,
):
    _patch_dirs(monkeypatch, tmp_path)
    (tmp_path / "sid1.session").write_text("claude_session_id=ccsid1\n")
    resolver.ccsid_pointer("ccsid1").parent.mkdir(parents=True, exist_ok=True)
    resolver.ccsid_pointer("ccsid1").write_text("sid1")

    resolver.detach_window("ccsid1", "sid1", source="claude")

    assert not resolver.ccsid_pointer("ccsid1").exists()
    assert resolver._parse(tmp_path / "sid1.session")["claude_session_id"] == ""


def test_detach_window_keeps_another_remaining_ccsid_as_the_current_one(
    monkeypatch, tmp_path,
):
    _patch_dirs(monkeypatch, tmp_path)
    (tmp_path / "sid1.session").write_text("claude_session_id=ccsid1\n")
    resolver.ccsid_pointer("ccsid1").parent.mkdir(parents=True, exist_ok=True)
    resolver.ccsid_pointer("ccsid1").write_text("sid1")
    resolver.ccsid_pointer("ccsid2").write_text("sid1")

    resolver.detach_window("ccsid1", "sid1", source="claude")

    assert resolver._parse(tmp_path / "sid1.session")["claude_session_id"] == "ccsid2"


def test_detach_window_removes_codex_pointer_and_clears_session_field(
    monkeypatch, tmp_path,
):
    _patch_dirs(monkeypatch, tmp_path)
    (tmp_path / "sid1.session").write_text("codex_session_id=cid1\n")
    resolver.codex_session_id_pointer("cid1").parent.mkdir(parents=True, exist_ok=True)
    resolver.codex_session_id_pointer("cid1").write_text("sid1")

    resolver.detach_window("cid1", "sid1", source="codex")

    assert not resolver.codex_session_id_pointer("cid1").exists()
    assert resolver._parse(tmp_path / "sid1.session")["codex_session_id"] == ""


def test_is_stale_window_true_for_missing_path():
    assert dispatch._is_stale_window(None) is True


def test_is_stale_window_true_for_nonexistent_file(tmp_path):
    assert dispatch._is_stale_window(tmp_path / "no-such-file") is True


def test_is_stale_window_true_past_the_cutoff(tmp_path):
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text("{}\n")
    old = time.time() - (dispatch.STALE_WINDOW_DAYS + 1) * 86400
    os.utime(transcript, (old, old))

    assert dispatch._is_stale_window(transcript) is True


def test_is_stale_window_false_within_the_cutoff(tmp_path):
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text("{}\n")

    assert dispatch._is_stale_window(transcript) is False


def test_detach_stale_attached_detaches_only_the_stale_window(monkeypatch, tmp_path):
    fresh = tmp_path / "fresh.jsonl"
    fresh.write_text("{}\n")
    stale = tmp_path / "stale.jsonl"
    stale.write_text("{}\n")
    old = time.time() - (dispatch.STALE_WINDOW_DAYS + 1) * 86400
    os.utime(stale, (old, old))

    monkeypatch.setattr(dispatch, "_read_config", lambda: {
        "owrap_context_manager_enabled": True,
    })
    monkeypatch.setattr(dispatch, "get_workspace_path", lambda: tmp_path)
    monkeypatch.setattr(
        dispatch, "all_attached_ccsid_pairs",
        lambda: [("fresh-ccsid", "sid-fresh"), ("stale-ccsid", "sid-stale")],
    )
    monkeypatch.setattr(dispatch, "all_attached_codex_session_id_pairs", lambda: [])
    monkeypatch.setattr(
        dispatch, "claude_transcript_path",
        lambda ccsid, ws: fresh if ccsid == "fresh-ccsid" else stale,
    )
    detached = []
    monkeypatch.setattr(
        dispatch, "detach_window",
        lambda window_id, sid, source: detached.append((window_id, sid, source)),
    )

    dispatch.detach_stale_attached()

    assert detached == [("stale-ccsid", "sid-stale", "claude")]
