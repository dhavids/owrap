import json
import os
import sys
import time
from unittest.mock import MagicMock, patch

import pytest

from owrap.manager import Manager


def test_ensure_daemon_starts_current_checkout(tmp_path):
    from owrap.utils.dispatch.pool import _ensure_daemon

    pid_file = tmp_path / "daemon.pid"
    lock_file = tmp_path / "daemon.lock"
    root = tmp_path / "checkout"
    root.mkdir()
    process = MagicMock(pid=3210)

    with (
        patch("owrap.utils.dispatch.pool.DAEMON_PID_FILE", pid_file),
        patch("owrap.utils.dispatch.pool.DAEMON_LOCK_FILE", lock_file),
        patch("owrap.utils.dispatch.pool.OWRAP_ROOT", root),
        patch(
            "owrap.utils.dispatch.pool.subprocess.Popen",
            return_value=process,
        ) as popen,
    ):
        _ensure_daemon()

    command = popen.call_args.args[0]
    assert command[0] == sys.executable
    assert command[1:] == ["-m", "owrap.runner", "daemon"]
    assert popen.call_args.kwargs["cwd"] == str(root)
    assert pid_file.read_text() == "3210"


def test_ensure_daemon_keeps_running_process(tmp_path):
    from owrap.utils.dispatch.pool import _ensure_daemon

    pid_file = tmp_path / "daemon.pid"
    pid_file.write_text(str(os.getpid()))

    with (
        patch("owrap.utils.dispatch.pool.DAEMON_PID_FILE", pid_file),
        patch(
            "owrap.utils.dispatch.pool.DAEMON_LOCK_FILE",
            tmp_path / "daemon.lock",
        ),
        patch("owrap.utils.dispatch.pool.subprocess.Popen") as popen,
    ):
        _ensure_daemon()

    popen.assert_not_called()


def test_dev_port_range_does_not_use_live_port():
    from owrap.utils.dispatch.pool import _next_port

    config = {"max_servers": 2, "server_port_base": 5096}
    with patch("owrap.utils.dispatch.pool._read_config", return_value=config):
        assert _next_port([]) == 5096
        assert _next_port([{"port": 5096}]) == 5097


def test_single_server_uses_configured_port():
    manager = Manager.__new__(Manager)
    with (
        patch("owrap.manager._read_config", return_value={"server_port_base": 5096}),
        patch.object(
            manager, "_kill_port_occupant", side_effect=RuntimeError("stopped"),
        ) as kill,
    ):
        with pytest.raises(RuntimeError, match="stopped"):
            manager.start()
    kill.assert_called_once_with(5096)


def test_pool_active_false_when_no_pool_file():
    from owrap.utils.dispatch.pool import _pool_active
    with patch("owrap.utils.dispatch.pool._read_config", return_value={"max_servers": 1, "min_servers": 2}):
        assert _pool_active() is False


def test_pool_active_true_when_configured():
    from owrap.utils.dispatch.pool import _pool_active
    with patch("owrap.utils.dispatch.pool._read_config", return_value={"max_servers": 3, "min_servers": 2}):
        assert _pool_active() is True


def test_shutdown_idle_respects_min_n(tmp_path):
    from owrap.utils.dispatch.pool import shutdown_idle

    pool = [
        {"pid": os.getpid(), "url": f"http://localhost:{4096+i}", "port": 4096+i, "last_used": 0}
        for i in range(3)
    ]
    fake_pool = tmp_path / "pool.json"
    fake_pool.write_text(json.dumps(pool))
    fake_lock = tmp_path / "pool.lock"

    with patch("owrap.utils.dispatch.pool.POOL_FILE", fake_pool), \
         patch("owrap.utils.dispatch.pool.POOL_LOCK_FILE", fake_lock), \
         patch("owrap.utils.dispatch.pool._is_alive", return_value=True), \
         patch("owrap.utils.dispatch.pool._is_responsive", return_value=True), \
         patch("os.kill"):
        shutdown_idle(idle_s=0, min_n=2)

    remaining = json.loads(fake_pool.read_text())
    assert len(remaining) == 2


def test_shutdown_idle_killed_counter(tmp_path):
    from owrap.utils.dispatch.pool import shutdown_idle

    pool = [
        {"pid": os.getpid(), "url": f"http://localhost:{4096+i}", "port": 4096+i, "last_used": 0}
        for i in range(4)
    ]
    fake_pool = tmp_path / "pool.json"
    fake_pool.write_text(json.dumps(pool))
    fake_lock = tmp_path / "pool.lock"

    with patch("owrap.utils.dispatch.pool.POOL_FILE", fake_pool), \
         patch("owrap.utils.dispatch.pool.POOL_LOCK_FILE", fake_lock), \
         patch("owrap.utils.dispatch.pool._is_alive", return_value=True), \
         patch("owrap.utils.dispatch.pool._is_responsive", return_value=True), \
         patch("os.kill"):
        shutdown_idle(idle_s=0, min_n=1)

    remaining = json.loads(fake_pool.read_text())
    assert len(remaining) == 1


def test_update_last_used(tmp_path):
    from owrap.utils.dispatch.pool import update_last_used

    before = time.time() - 100
    pool = [{"pid": 999, "url": "http://localhost:4096", "port": 4096, "last_used": before}]
    fake_pool = tmp_path / "pool.json"
    fake_pool.write_text(json.dumps(pool))
    fake_lock = tmp_path / "pool.lock"

    with patch("owrap.utils.dispatch.pool.POOL_FILE", fake_pool), \
         patch("owrap.utils.dispatch.pool.POOL_LOCK_FILE", fake_lock):
        update_last_used("http://localhost:4096")

    updated = json.loads(fake_pool.read_text())
    assert updated[0]["last_used"] > before


def test_trim_logs_keeps_max(tmp_path):
    for i in range(5):
        f = tmp_path / f"task_{i:03d}.log"
        f.write_text("x")
        os.utime(f, (i, i))

    Manager._trim_logs(tmp_path, "*.log", max_keep=3)
    remaining = sorted(tmp_path.glob("*.log"))
    assert len(remaining) == 3
    names = {f.name for f in remaining}
    assert "task_002.log" in names
    assert "task_003.log" in names
    assert "task_004.log" in names


def test_shutdown_idle_preserves_reserved_entries(tmp_path):
    from owrap.utils.dispatch.pool import shutdown_idle

    now = time.time()
    pool = [
        {
            "pid": os.getpid(), "url": "http://localhost:4096",
            "port": 4096, "last_used": now, "reserved": 1,
        },
        {
            "pid": os.getpid(), "url": "http://localhost:4097",
            "port": 4097, "last_used": 0, "reserved": 0,
        },
    ]
    fake_pool = tmp_path / "pool.json"
    fake_pool.write_text(json.dumps(pool))
    fake_lock = tmp_path / "pool.lock"

    with patch("owrap.utils.dispatch.pool.POOL_FILE", fake_pool), \
         patch("owrap.utils.dispatch.pool.POOL_LOCK_FILE", fake_lock), \
         patch("owrap.utils.dispatch.pool._is_alive", return_value=True), \
         patch("owrap.utils.dispatch.pool._is_responsive", return_value=True), \
         patch("owrap.utils.dispatch.pool._active_load", return_value=0), \
         patch("os.kill"):
        shutdown_idle(idle_s=0, min_n=0)

    remaining = json.loads(fake_pool.read_text())
    assert len(remaining) == 1
    assert remaining[0]["url"] == "http://localhost:4096"
    assert remaining[0]["reserved"] == 1


def test_record_unresponsive_kills_at_threshold(tmp_path):
    from owrap.utils.dispatch.pool import record_unresponsive
    from unittest.mock import patch

    pool = [{"pid": os.getpid(), "url": "http://localhost:4096", "port": 4096, "last_used": 0}]
    fake_pool = tmp_path / "pool.json"
    fake_pool.write_text(json.dumps(pool))
    fake_lock = tmp_path / "pool.lock"

    with patch("owrap.utils.dispatch.pool.POOL_FILE", fake_pool), \
         patch("owrap.utils.dispatch.pool.POOL_LOCK_FILE", fake_lock):
        first = record_unresponsive("http://localhost:4096", threshold=2)
        assert first is False
        remaining = json.loads(fake_pool.read_text())
        assert len(remaining) == 1
        assert remaining[0]["unresponsive_count"] == 1
        assert remaining[0].get("draining") is not True

        second = record_unresponsive("http://localhost:4096", threshold=2)
        assert second is True
        remaining = json.loads(fake_pool.read_text())
        assert len(remaining) == 1
        assert remaining[0]["draining"] is True


def test_record_unresponsive_custom_threshold_one(tmp_path):
    from owrap.utils.dispatch.pool import record_unresponsive
    from unittest.mock import patch

    pool = [{"pid": os.getpid(), "url": "http://localhost:4096", "port": 4096, "last_used": 0}]
    fake_pool = tmp_path / "pool.json"
    fake_pool.write_text(json.dumps(pool))
    fake_lock = tmp_path / "pool.lock"

    with patch("owrap.utils.dispatch.pool.POOL_FILE", fake_pool), \
         patch("owrap.utils.dispatch.pool.POOL_LOCK_FILE", fake_lock):
        result = record_unresponsive("http://localhost:4096", threshold=1)
        assert result is True
        remaining = json.loads(fake_pool.read_text())
        assert len(remaining) == 1
        assert remaining[0]["draining"] is True


def test_record_responsive_resets_counter(tmp_path):
    from owrap.utils.dispatch.pool import record_responsive
    from unittest.mock import patch

    pool = [{"pid": os.getpid(), "url": "http://localhost:4096", "port": 4096, "last_used": 0, "unresponsive_count": 1}]
    fake_pool = tmp_path / "pool.json"
    fake_pool.write_text(json.dumps(pool))
    fake_lock = tmp_path / "pool.lock"

    with patch("owrap.utils.dispatch.pool.POOL_FILE", fake_pool), \
         patch("owrap.utils.dispatch.pool.POOL_LOCK_FILE", fake_lock):
        record_responsive("http://localhost:4096")

    remaining = json.loads(fake_pool.read_text())
    assert remaining[0]["unresponsive_count"] == 0


def test_record_unresponsive_unknown_url_noop(tmp_path):
    from owrap.utils.dispatch.pool import record_unresponsive
    from unittest.mock import patch

    pool = [{"pid": os.getpid(), "url": "http://localhost:4096", "port": 4096, "last_used": 0}]
    fake_pool = tmp_path / "pool.json"
    fake_pool.write_text(json.dumps(pool))
    fake_lock = tmp_path / "pool.lock"

    with patch("owrap.utils.dispatch.pool.POOL_FILE", fake_pool), \
         patch("owrap.utils.dispatch.pool.POOL_LOCK_FILE", fake_lock), \
         patch("os.kill") as mock_kill:
        result = record_unresponsive("http://localhost:9999", threshold=1)
        assert result is False
        mock_kill.assert_not_called()

    remaining = json.loads(fake_pool.read_text())
    assert remaining == pool


def test_pick_server_force_kills_stale_hung_entry(tmp_path):
    from owrap.utils.dispatch.pool import pick_server
    from unittest.mock import patch

    stale_pid = 424242
    pool = [{
        "pid": stale_pid, "url": "http://localhost:4096",
        "port": 4096, "last_used": 0,
    }]
    fake_pool = tmp_path / "pool.json"
    fake_pool.write_text(json.dumps(pool))
    fake_lock = tmp_path / "pool.lock"

    new_entry = {
        "port": 4096, "url": "http://localhost:4096",
        "pid": 55555, "last_used": time.time(),
    }

    with patch("owrap.utils.dispatch.pool.POOL_FILE", fake_pool), \
         patch("owrap.utils.dispatch.pool.POOL_LOCK_FILE", fake_lock), \
         patch("owrap.utils.dispatch.pool._pool_active", return_value=True), \
         patch("owrap.utils.dispatch.pool._ensure_daemon"), \
         patch("owrap.utils.dispatch.pool.ensure_min_servers"), \
         patch("owrap.utils.dispatch.pool._is_alive", side_effect=[True, True, False, False]), \
         patch("owrap.utils.dispatch.pool._is_responsive", return_value=False), \
         patch("owrap.utils.dispatch.pool._next_port", return_value=4096), \
         patch("owrap.utils.dispatch.pool._start_server", return_value=new_entry), \
         patch("owrap.utils.dispatch.pool._wait_responsive"), \
         patch("os.kill") as mock_kill:
        url = pick_server("msg")

    assert url == "http://localhost:4096"
    mock_kill.assert_called_once_with(stale_pid, 15)

    remaining = json.loads(fake_pool.read_text())
    assert len(remaining) == 1
    assert remaining[0]["pid"] == 55555


def test_pick_server_escalates_to_sigkill_if_stale_wont_die(tmp_path):
    from owrap.utils.dispatch.pool import pick_server
    from unittest.mock import patch

    stale_pid = 424243
    pool = [{
        "pid": stale_pid, "url": "http://localhost:4096",
        "port": 4096, "last_used": 0,
    }]
    fake_pool = tmp_path / "pool.json"
    fake_pool.write_text(json.dumps(pool))
    fake_lock = tmp_path / "pool.lock"

    new_entry = {
        "port": 4096, "url": "http://localhost:4096",
        "pid": 55556, "last_used": 0,
    }

    time_values = iter([100.0, 100.0, 103.0])
    def fake_time():
        return next(time_values, 999.0)

    with patch("owrap.utils.dispatch.pool.POOL_FILE", fake_pool), \
         patch("owrap.utils.dispatch.pool.POOL_LOCK_FILE", fake_lock), \
         patch("owrap.utils.dispatch.pool._pool_active", return_value=True), \
         patch("owrap.utils.dispatch.pool._ensure_daemon"), \
         patch("owrap.utils.dispatch.pool.ensure_min_servers"), \
         patch("owrap.utils.dispatch.pool._is_alive", return_value=True), \
         patch("owrap.utils.dispatch.pool._is_responsive", return_value=False), \
         patch("owrap.utils.dispatch.pool._next_port", return_value=4096), \
         patch("owrap.utils.dispatch.pool._start_server", return_value=new_entry), \
         patch("owrap.utils.dispatch.pool._wait_responsive"), \
         patch("owrap.utils.dispatch.pool.time.time", side_effect=fake_time), \
         patch("owrap.utils.dispatch.pool.time.sleep"), \
         patch("os.kill") as mock_kill:
        pick_server("msg")

    mock_kill.assert_any_call(stale_pid, 15)
    mock_kill.assert_any_call(stale_pid, 9)
