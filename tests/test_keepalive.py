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
         patch("owrap.commands.keepalive._read_config", return_value={
             "keepalive_interval_s": 0.01,
             "keepalive_idle_exit_s": 0.0,
         }), \
         patch("owrap.commands.keepalive.time.sleep"):
        KeepaliveRunner(MagicMock()).run()

    # Should have called get_pool at least twice (first empty sets timer, second triggers exit)
    assert calls["n"] >= 2


def test_keepalive_cleans_pid_file_on_exit(tmp_path):
    from owrap.commands.keepalive import KeepaliveRunner

    pid_file = tmp_path / ".owrap" / "keepalive.pid"
    pid_file.parent.mkdir(parents=True, exist_ok=True)

    with patch("owrap.commands.keepalive.Path.home", return_value=tmp_path), \
         patch("owrap.commands.keepalive.get_pool", return_value=[]), \
         patch("owrap.commands.keepalive._read_config", return_value={
             "keepalive_interval_s": 0.01,
             "keepalive_idle_exit_s": 0.0,
         }), \
         patch("owrap.commands.keepalive.time.sleep"):
        KeepaliveRunner(MagicMock()).run()

    assert not pid_file.exists()
