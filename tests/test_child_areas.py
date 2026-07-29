from unittest.mock import MagicMock, patch

import pytest

from owrap.session.start import StartRunner, SpawnRunner


@pytest.fixture
def session_resolver_dir(tmp_path, monkeypatch):
    """session_resolver.SESSIONS_DIR, BY_CCSID_DIR, and BY_OPENCODE_RUN_ID_DIR
    are all bound at import time (not covered by the isolate_owrap_dirs
    autouse fixture), and multiple modules (start.py, stop.py) hold their
    own separate direct-import bindings to BY_CCSID_DIR/BY_OPENCODE_RUN_ID_DIR
    that patching session_resolver's copy alone does NOT affect — redirect
    every one of them to a tmp dir, in every module that imports them, or
    tests here can silently write into the REAL production session
    pointer directory."""
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    by_ccsid_dir = sessions_dir / "by_ccsid"
    by_oid_dir = sessions_dir / "by_opencode_run_id"
    monkeypatch.setattr("owrap.utils.session_resolver.SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr("owrap.utils.session_resolver.BY_CCSID_DIR", by_ccsid_dir)
    monkeypatch.setattr("owrap.utils.session_resolver.BY_OPENCODE_RUN_ID_DIR", by_oid_dir)
    monkeypatch.setattr("owrap.session.start.BY_CCSID_DIR", by_ccsid_dir)
    monkeypatch.setattr("owrap.session.stop.BY_CCSID_DIR", by_ccsid_dir)
    return sessions_dir


def _write_session(sessions_dir, sid, research=None, area=None):
    lines = [f"session_id={sid}"]
    if research:
        lines.append(f"research={research}")
    if area:
        lines.append(f"area={area}")
    (sessions_dir / f"{sid}.session").write_text("\n".join(lines) + "\n")


def _read_session(sessions_dir, sid):
    data = {}
    for line in (sessions_dir / f"{sid}.session").read_text().splitlines():
        k, v = line.split("=", 1)
        data[k] = v
    return data


# ---------------- StartRunner: child-area concatenation ----------------

def test_start_child_without_area_errors(session_resolver_dir, mock_manager, capsys):
    with pytest.raises(SystemExit) as exc:
        StartRunner(mock_manager).run(session_id="sid1", research="myres", child="kid")
    assert exc.value.code == 1
    assert "requires an area to be given too" in capsys.readouterr().err


def test_start_child_with_area_concatenates(tmp_path, session_resolver_dir, mock_manager, monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    mock_manager.create_context = MagicMock()
    mock_manager._housekeeping = MagicMock()
    mock_manager.refresh_context_plan = MagicMock()
    mock_manager.start_watchdog = MagicMock()

    with patch("owrap.session.start.SESSION_DIR", tmp_path), \
          patch("owrap.session.start._read_config",
               return_value={"research_root": str(tmp_path / "research"), "max_servers": 1}), \
         patch("owrap.session.start.get_workspace_config", return_value={}), \
         patch("owrap.session.start.print_orientation"), \
         patch("owrap.utils.pool._pool_active", return_value=True), \
         patch("owrap.utils.pool.ensure_min_servers"), \
         patch("owrap.utils.pool._ensure_keepalive"):
        with pytest.raises(SystemExit) as exc:
            StartRunner(mock_manager).run(session_id="sid2", research="myres", area="parent", child="kid")

    assert exc.value.code == 0
    assert _read_session(session_resolver_dir, "sid2")["area"] == "parent-kid"


# ---------------- SpawnRunner ----------------

def test_spawn_no_active_session_errors(session_resolver_dir, mock_manager, capsys):
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(SystemExit) as exc:
            SpawnRunner(mock_manager).run("kid")
    assert exc.value.code == 1
    assert "no active session" in capsys.readouterr().err


def test_spawn_without_area_errors(session_resolver_dir, mock_manager, capsys):
    _write_session(session_resolver_dir, "spawnsid", research="myres")
    with patch.dict("os.environ", {"SESSION_ID": "spawnsid"}, clear=True):
        with pytest.raises(SystemExit) as exc:
            SpawnRunner(mock_manager).run("kid")
    assert exc.value.code == 1
    assert "no research/area set" in capsys.readouterr().err


def test_spawn_success_concatenates_and_prints(tmp_path, session_resolver_dir, mock_manager, capsys):
    _write_session(session_resolver_dir, "spawnsid", research="myres", area="parent")
    with patch.dict("os.environ", {"SESSION_ID": "spawnsid"}, clear=True), \
         patch("owrap.session.start._read_config",
               return_value={"research_root": str(tmp_path / "research")}), \
         patch("owrap.session.start.print_orientation"):
        with pytest.raises(SystemExit) as exc:
            SpawnRunner(mock_manager).run("kid")
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "Spawned child area 'parent-kid' (parent: parent) under research 'myres'" in out
    assert _read_session(session_resolver_dir, "spawnsid")["area"] == "parent-kid"
