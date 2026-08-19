import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


def test_stop_force_kills_servers_via_kill_servers_runner(tmp_path):
    """--force must actually kill servers (was calling undefined Manager.stop_all and crashing)."""
    from owrap.session.stop import StopRunner

    fake_session_dir = tmp_path / "owrap_home"
    fake_session_dir.mkdir()
    fake_by_ccsid = tmp_path / "by_ccsid"

    with patch("owrap.session.stop.SESSION_DIR", fake_session_dir), \
         patch("owrap.session.stop.BY_CCSID_DIR", fake_by_ccsid), \
         patch("owrap.session.stop.list_sessions", return_value=[]), \
         patch("owrap.session.stop.KillServersRunner") as mock_ksr_cls:
        runner = StopRunner(manager=None)
        runner.run(force=True, no_exit=True)

    mock_ksr_cls.assert_called_once_with()
    mock_ksr_cls.return_value.run.assert_called_once_with()


def test_trim_command_removed():
    """owrap trim was removed (it only ever called an undefined Manager.trim_idle_servers)."""
    with patch.object(sys, "argv", ["owrap", "trim"]):
        from owrap.runner import main as runner_main
        with pytest.raises(SystemExit) as exc_info:
            runner_main()
        assert exc_info.value.code != 0


def test_kill_servers_logs_via_rtlog(tmp_path, monkeypatch):
    from owrap.session.stop import KillServersRunner
    alive_pid = os.getpid()
    fake_pool = [{"pid": alive_pid, "port": 4096, "url": "http://127.0.0.1:4096"}]

    with patch("owrap.utils.pool._read_pool", return_value=fake_pool), \
         patch("owrap.session.stop._pid_alive", return_value=True), \
         patch("owrap.session.stop._kill_pid", return_value=True), \
         patch("owrap.session.stop._wait_dead", return_value=None), \
         patch("owrap.utils.rtlog.log") as mock_log, \
         patch("owrap.session.stop.RUNNING_DIR", tmp_path / "running"), \
         patch("owrap.session.stop.RECENTLY_DONE_DIR", tmp_path / "done"), \
         patch("owrap.session.stop.SERVERS_DIR", tmp_path / "servers"), \
         patch("owrap.session.stop.KEEPALIVE_PID_FILE", tmp_path / "ka.pid"), \
         patch("owrap.utils.paths.STATS_FILE", tmp_path / "stats.json"):
        KillServersRunner().run()

    mock_log.assert_called_once()
    call = mock_log.call_args
    assert call[0][0] == "server.kill"
    assert call[1].get("reason") == "killservers"


def test_kill_servers_stops_keepalive(tmp_path, monkeypatch):
    from owrap.session.stop import KillServersRunner
    alive_pid = os.getpid()
    ka_pid_file = tmp_path / "keepalive.pid"
    ka_pid_file.write_text(str(alive_pid))

    with patch("owrap.utils.pool._read_pool", return_value=[]), \
         patch("owrap.session.stop._pid_alive", return_value=True), \
         patch("owrap.session.stop._kill_pid", return_value=True) as mock_kill, \
         patch("owrap.session.stop._wait_dead", return_value=None), \
         patch("owrap.session.stop.RUNNING_DIR", tmp_path / "running"), \
         patch("owrap.session.stop.RECENTLY_DONE_DIR", tmp_path / "done"), \
         patch("owrap.session.stop.SERVERS_DIR", tmp_path / "servers"), \
         patch("owrap.session.stop.KEEPALIVE_PID_FILE", ka_pid_file), \
         patch("owrap.utils.paths.STATS_FILE", tmp_path / "stats.json"):
        KillServersRunner().run()

    mock_kill.assert_called_with(alive_pid)
    assert not ka_pid_file.exists()


def test_kill_servers_resets_stats(tmp_path, monkeypatch):
    import json
    from owrap.session.stop import KillServersRunner
    stats_file = tmp_path / "stats.json"
    stats_file.write_text(json.dumps({
        "dispatched": 5, "succeeded": 3, "failed": 1,
        "stalled": 1, "timed_out": 2,
    }))

    with patch("owrap.utils.pool._read_pool", return_value=[]), \
         patch("owrap.session.stop._pid_alive", return_value=False), \
         patch("owrap.session.stop._kill_pid", return_value=True), \
         patch("owrap.session.stop._wait_dead", return_value=None), \
         patch("owrap.session.stop.RUNNING_DIR", tmp_path / "running"), \
         patch("owrap.session.stop.RECENTLY_DONE_DIR", tmp_path / "done"), \
         patch("owrap.session.stop.SERVERS_DIR", tmp_path / "servers"), \
         patch("owrap.session.stop.KEEPALIVE_PID_FILE", tmp_path / "ka.pid"), \
         patch("owrap.utils.paths.STATS_FILE", stats_file):
        KillServersRunner().run()

    data = json.loads(stats_file.read_text())
    assert data["dispatched"] == 0
    assert data["succeeded"] == 0
    assert data["failed"] == 0
    assert data["stalled"] == 0
    assert data["timed_out"] == 0
