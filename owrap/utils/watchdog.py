import json
import os
import time
import threading
from pathlib import Path

from ..constants import STALL_NOTIFY_S, WATCHDOG_POLL_S
from .paths import _read_config


class Watchdog:
    def __init__(self, log_path, kill_callback, notify_callback, kill_after_s,
                 stall_s=None, poll_s=None, no_output_s=None, unresponsive_callback=None):
        _cfg = _read_config()
        self._log_path = Path(log_path)
        self._kill_callback = kill_callback
        self._notify_callback = notify_callback
        self._kill_after_s = kill_after_s
        self._stall_s = stall_s if stall_s is not None else float(_cfg.get("stall_notify_s", STALL_NOTIFY_S))
        self._poll_s = poll_s if poll_s is not None else float(_cfg.get("watchdog_poll_s", WATCHDOG_POLL_S))
        self._thread = None
        self._stop_event = threading.Event()
        self._state = "healthy"
        self._stall_since = None
        self._last_mtime = 0
        self._last_size = 0
        self._last_change_time = time.time()
        self._no_output_s = no_output_s
        self._unresponsive_callback = unresponsive_callback
        self._no_output_fired = False
        self._has_output = False
        self._start_time = time.time()
        try:
            self._initial_size = os.path.getsize(log_path)
        except OSError:
            self._initial_size = 0

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=self._poll_s + 1)

    def _check_file_changed(self):
        try:
            stat = os.stat(self._log_path)
            if stat.st_mtime != self._last_mtime or stat.st_size != self._last_size:
                self._last_mtime = stat.st_mtime
                self._last_size = stat.st_size
                return True
        except OSError:
            pass
        return False

    def _run(self):
        while not self._stop_event.is_set():
            self._stop_event.wait(self._poll_s)
            if self._stop_event.is_set():
                break

            now = time.time()
            if self._check_file_changed():
                self._last_change_time = now
                if self._state == "stalled":
                    self._state = "healthy"
                    self._stall_since = None
                    self._notify_callback("healthy")
            else:
                elapsed = now - self._last_change_time
                if self._state == "healthy" and elapsed >= self._stall_s:
                    self._state = "stalled"
                    self._stall_since = now
                    self._notify_callback("stalled")
                elif self._state == "stalled" and self._stall_since and now - self._stall_since >= self._kill_after_s:
                    self._kill_callback()
                    break

            if self._no_output_s and not self._no_output_fired:
                if not self._has_output:
                    try:
                        if os.path.getsize(self._log_path) > self._initial_size:
                            self._has_output = True
                    except OSError:
                        pass
                if not self._has_output and (now - self._start_time) >= self._no_output_s:
                    self._no_output_fired = True
                    if self._unresponsive_callback:
                        self._unresponsive_callback()
                    break


def write_sentinel_health(sentinel_path, health_state):
    try:
        if sentinel_path and sentinel_path.exists():
            data = json.loads(sentinel_path.read_text())
            data["health"] = health_state
            sentinel_path.write_text(json.dumps(data))
    except Exception:
        pass
