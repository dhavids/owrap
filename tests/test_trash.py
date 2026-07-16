from datetime import datetime, timedelta
from unittest.mock import patch

import pytest


def _patch_paths(tmp_path):
    trash_dir = tmp_path / "trash"
    sessions_dir = tmp_path / "sessions"
    runtime_dir = tmp_path / "runtime"
    docs_dir = tmp_path / "docs"
    sessions_dir.mkdir(exist_ok=True)
    runtime_dir.mkdir(exist_ok=True)
    docs_dir.mkdir(exist_ok=True)
    return trash_dir, sessions_dir, runtime_dir, docs_dir


def test_move_to_trash_moves_all_pieces(tmp_path):
    from owrap.utils import trash as trash_mod

    trash_dir, sessions_dir, runtime_dir, docs_dir = _patch_paths(tmp_path)
    sid = "abc123"

    (sessions_dir / f"{sid}.session").write_text("session_id=abc123\n")
    sess_docs = docs_dir / "sessions" / sid
    sess_docs.mkdir(parents=True)
    (sess_docs / "context.md").write_text("hello")
    (runtime_dir / sid).mkdir()
    (runtime_dir / sid / "state.json").write_text("{}")
    (docs_dir / f"context_{sid}.md").write_text("ctx")
    (docs_dir / f"context_{sid}.lock").write_text("")

    with patch.object(trash_mod, "TRASH_DIR", trash_dir), \
         patch.object(trash_mod, "SESSIONS_DIR", sessions_dir), \
         patch.object(trash_mod, "RUNTIME_DIR", runtime_dir), \
         patch.object(trash_mod, "DOCS_DIR", docs_dir), \
         patch.object(trash_mod, "session_dir", lambda s: docs_dir / "sessions" / s):
        result = trash_mod.move_to_trash(sid)

    assert result == trash_dir / sid
    assert (trash_dir / sid / "session").exists()
    assert not (sessions_dir / f"{sid}.session").exists()
    assert (trash_dir / sid / "docs_sessions" / "context.md").exists()
    assert not sess_docs.exists()
    assert (trash_dir / sid / "runtime" / "state.json").exists()
    assert not (runtime_dir / sid).exists()
    assert (trash_dir / sid / "context" / f"context_{sid}.md").exists()
    assert (trash_dir / sid / "context" / f"context_{sid}.lock").exists()
    assert (trash_dir / sid / "trashed_at").exists()


def test_restore_from_trash_round_trips(tmp_path):
    from owrap.utils import trash as trash_mod

    trash_dir, sessions_dir, runtime_dir, docs_dir = _patch_paths(tmp_path)
    sid = "def456"

    (sessions_dir / f"{sid}.session").write_text("session_id=def456\n")
    sess_docs = docs_dir / "sessions" / sid
    sess_docs.mkdir(parents=True)
    (sess_docs / "context.md").write_text("hello")
    (runtime_dir / sid).mkdir()

    with patch.object(trash_mod, "TRASH_DIR", trash_dir), \
         patch.object(trash_mod, "SESSIONS_DIR", sessions_dir), \
         patch.object(trash_mod, "RUNTIME_DIR", runtime_dir), \
         patch.object(trash_mod, "DOCS_DIR", docs_dir), \
         patch.object(trash_mod, "session_dir", lambda s: docs_dir / "sessions" / s):
        trash_mod.move_to_trash(sid)
        trash_mod.restore_from_trash(sid)

    assert (sessions_dir / f"{sid}.session").exists()
    assert (sess_docs / "context.md").exists()
    assert (runtime_dir / sid).exists()
    assert not (trash_dir / sid).exists()


def test_restore_from_trash_missing_raises(tmp_path):
    from owrap.utils import trash as trash_mod

    trash_dir, sessions_dir, runtime_dir, docs_dir = _patch_paths(tmp_path)

    with patch.object(trash_mod, "TRASH_DIR", trash_dir):
        with pytest.raises(FileNotFoundError):
            trash_mod.restore_from_trash("no-such-session")


def test_sweep_trash_removes_only_past_retention(tmp_path):
    from owrap.utils import trash as trash_mod

    trash_dir = tmp_path / "trash"
    trash_dir.mkdir()

    old_entry = trash_dir / "old_session"
    old_entry.mkdir()
    (old_entry / "trashed_at").write_text((datetime.now() - timedelta(days=45)).isoformat())

    recent_entry = trash_dir / "recent_session"
    recent_entry.mkdir()
    (recent_entry / "trashed_at").write_text(datetime.now().isoformat())

    with patch.object(trash_mod, "TRASH_DIR", trash_dir), \
         patch.object(trash_mod, "_read_config", return_value={}):
        removed = trash_mod.sweep_trash()

    assert removed == 1
    assert not old_entry.exists()
    assert recent_entry.exists()


def test_sweep_trash_respects_custom_retention_arg(tmp_path):
    from owrap.utils import trash as trash_mod

    trash_dir = tmp_path / "trash"
    trash_dir.mkdir()

    entry = trash_dir / "s1"
    entry.mkdir()
    (entry / "trashed_at").write_text((datetime.now() - timedelta(days=5)).isoformat())

    with patch.object(trash_mod, "TRASH_DIR", trash_dir):
        removed = trash_mod.sweep_trash(retention_days=1)

    assert removed == 1
    assert not entry.exists()
