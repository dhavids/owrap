import json
import time
from pathlib import Path
from unittest.mock import MagicMock


def test_watchdog_notifies_stall_on_no_growth(tmp_path):
    from owrap.utils.watchdog import Watchdog

    log_file = tmp_path / "test.log"
    log_file.write_text("initial")

    notify_calls = []
    kill_mock = MagicMock()

    wd = Watchdog(log_file, kill_mock, lambda s: notify_calls.append(s),
                  kill_after_s=10, stall_s=0.05, poll_s=0.02)
    wd.start()
    time.sleep(0.25)
    wd.stop()

    assert "stalled" in notify_calls


def test_watchdog_resets_on_file_growth(tmp_path):
    from owrap.utils.watchdog import Watchdog

    log_file = tmp_path / "test.log"
    log_file.write_text("initial")

    notify_calls = []

    wd = Watchdog(log_file, MagicMock(), lambda s: notify_calls.append(s),
                  kill_after_s=10, stall_s=0.05, poll_s=0.02)
    wd.start()
    time.sleep(0.15)
    log_file.write_text("updated content after stall")
    time.sleep(0.15)
    wd.stop()

    assert "stalled" in notify_calls
    assert "healthy" in notify_calls


def test_watchdog_kills_after_kill_delay(tmp_path):
    from owrap.utils.watchdog import Watchdog

    log_file = tmp_path / "test.log"
    log_file.write_text("x")

    kill_mock = MagicMock()

    wd = Watchdog(log_file, kill_mock, MagicMock(),
                  kill_after_s=0.05, stall_s=0.02, poll_s=0.01)
    wd.start()
    time.sleep(0.4)
    wd.stop()

    kill_mock.assert_called_once()


def test_watchdog_stop_cancels_kill(tmp_path):
    from owrap.utils.watchdog import Watchdog

    log_file = tmp_path / "test.log"
    log_file.write_text("x")

    kill_mock = MagicMock()

    wd = Watchdog(log_file, kill_mock, MagicMock(),
                  kill_after_s=5.0, stall_s=0.02, poll_s=0.01)
    wd.start()
    time.sleep(0.1)
    wd.stop()

    kill_mock.assert_not_called()


def test_write_sentinel_health(tmp_path):
    from owrap.utils.watchdog import write_sentinel_health

    sentinel = tmp_path / "sentinel.json"
    sentinel.write_text(json.dumps({"task_id": "1", "health": "healthy"}))

    write_sentinel_health(sentinel, "stalled")

    data = json.loads(sentinel.read_text())
    assert data["health"] == "stalled"
