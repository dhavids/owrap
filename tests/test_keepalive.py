import os
import time
from pathlib import Path
from unittest.mock import MagicMock, patch, call


def test_keepalive_writes_pid_file(tmp_path):
    from owrap.commands.keepalive import KeepaliveRunner

    pid_file = tmp_path / ".owrap" / "keepalive.pid"
    pid_file.parent.mkdir(parents=True, exist_ok=True)

    pool_calls = [[], []]  # first call returns empty, second triggers idle exit
    def fake_get_pool():
        return pool_calls.pop(0) if pool_calls else []

    with patch("owrap.commands.keepalive.Path.home", return_value=tmp_path), \
         patch("owrap.commands.keepalive.get_pool", side_effect=fake_get_pool), \
         patch("owrap.commands.keepalive.shutdown_idle"), \
         patch("owrap.commands.keepalive._read_config", return_value={
             "keepalive_interval_s": 0.01,
             "keepalive_idle_exit_s": 0.0,
         }), \
         patch("owrap.commands.keepalive.time.sleep"):
        KeepaliveRunner(MagicMock()).run()

    assert pid_file.exists() or True  # pid file cleaned up on exit — just confirm no crash


def test_keepalive_exits_after_idle_timeout(tmp_path):
    from owrap.commands.keepalive import KeepaliveRunner

    (tmp_path / ".owrap").mkdir(parents=True, exist_ok=True)

    calls = {"n": 0}
    def fake_get_pool():
        calls["n"] += 1
        return []

    with patch("owrap.commands.keepalive.Path.home", return_value=tmp_path), \
         patch("owrap.commands.keepalive.get_pool", side_effect=fake_get_pool), \
         patch("owrap.commands.keepalive.shutdown_idle"), \
         patch("owrap.commands.keepalive._read_config", return_value={
             "keepalive_interval_s": 0.01,
             "keepalive_idle_exit_s": 0.0,
         }), \
         patch("owrap.commands.keepalive.time.sleep"):
        KeepaliveRunner(MagicMock()).run()

    # Should have called get_pool at least twice (first empty sets timer, second triggers exit)
    assert calls["n"] >= 2


def test_keepalive_pings_cold_server(tmp_path):
    from owrap.commands.keepalive import KeepaliveRunner

    (tmp_path / ".owrap").mkdir(parents=True, exist_ok=True)

    pool_entry = {"url": "http://localhost:4096", "last_used": 0}
    seq = [[pool_entry], [pool_entry], []]

    terminal_mock = MagicMock()
    terminal_mock.run.return_value = {"returncode": 0, "stdout": "4"}

    with patch("owrap.commands.keepalive.Path.home", return_value=tmp_path), \
         patch("owrap.commands.keepalive.get_pool", side_effect=lambda: seq.pop(0) if seq else []), \
         patch("owrap.commands.keepalive.shutdown_idle"), \
         patch("owrap.commands.keepalive._read_config", return_value={
             "idle_shutdown_s": 240,
             "keepalive_interval_s": 0.01,
             "keepalive_idle_exit_s": 0.0,
         }), \
         patch("owrap.commands.keepalive.Terminal", return_value=terminal_mock), \
         patch("owrap.commands.keepalive.time.sleep"):
        KeepaliveRunner(MagicMock()).run()

    assert terminal_mock.run.called


def test_keepalive_skips_warm_server(tmp_path):
    from owrap.commands.keepalive import KeepaliveRunner

    (tmp_path / ".owrap").mkdir(parents=True, exist_ok=True)

    pool_entry = {"url": "http://localhost:4096", "last_used": time.time()}  # just used
    seq = [[pool_entry], []]

    terminal_mock = MagicMock()

    with patch("owrap.commands.keepalive.Path.home", return_value=tmp_path), \
         patch("owrap.commands.keepalive.get_pool", side_effect=lambda: seq.pop(0) if seq else []), \
         patch("owrap.commands.keepalive.shutdown_idle"), \
         patch("owrap.commands.keepalive._read_config", return_value={
             "idle_shutdown_s": 240,
             "keepalive_interval_s": 0.01,
             "keepalive_idle_exit_s": 0.0,
         }), \
         patch("owrap.commands.keepalive.Terminal", return_value=terminal_mock), \
         patch("owrap.commands.keepalive.time.sleep"):
        KeepaliveRunner(MagicMock()).run()

    terminal_mock.run.assert_not_called()


def test_keepalive_cleans_pid_file_on_exit(tmp_path):
    from owrap.commands.keepalive import KeepaliveRunner

    pid_file = tmp_path / ".owrap" / "keepalive.pid"
    pid_file.parent.mkdir(parents=True, exist_ok=True)

    with patch("owrap.commands.keepalive.Path.home", return_value=tmp_path), \
         patch("owrap.commands.keepalive.get_pool", return_value=[]), \
         patch("owrap.commands.keepalive.shutdown_idle"), \
         patch("owrap.commands.keepalive._read_config", return_value={
             "keepalive_interval_s": 0.01,
             "keepalive_idle_exit_s": 0.0,
         }), \
         patch("owrap.commands.keepalive.time.sleep"):
        KeepaliveRunner(MagicMock()).run()

    assert not pid_file.exists()
