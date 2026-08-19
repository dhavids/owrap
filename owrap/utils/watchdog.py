import json
import os
import re
import time
import threading
from pathlib import Path

from ..constants import (
    STALL_NOTIFY_S, WATCHDOG_POLL_S, SCRIPT_STALL_MULTIPLIER,
    WATCHDOG_UNRESPONSIVE_MSG, WATCHDOG_RETRY_HINT_FILE_TASK,
    WATCHDOG_RETRY_HINT_OWRAP_F, WATCHDOG_UNRESPONSIVE_EVICT_SUFFIX,
    WATCHDOG_INFRA_FAILURE_MSG, WATCHDOG_KILL_STALL_MSG,
)
from .paths import _read_config
from . import rtlog


_SCRIPT_TRIGGER_RE = re.compile(
    r'(?i)\b(run|running|execute|executing|writ(?:e|ing)|creat(?:e|ing))\b'
)
_SCRIPT_WORD_RE = re.compile(r'(?i)\bscript\b')

_WRITE_TRIGGER_RE = re.compile(r'(?i)\b(writ(?:e|ing)|execut(?:e|ing))\b')
_WRITE_TARGET_RE = re.compile(
    r'(?i)\b(notebook|entire\s+(file|notebook)|full\s+file|whole\s+file)\b'
)

_TASKLIKE_KINDS = ("task", "exec")


def write_sentinel_health(sentinel_path, health_state):
    """
    Update the health field in a sentinel JSON file.
    """
    try:
        if sentinel_path and sentinel_path.exists():
            data = json.loads(sentinel_path.read_text())
            data["health"] = health_state
            sentinel_path.write_text(json.dumps(data))
    except Exception:
        pass


def strip_boilerplate(text: str) -> str:
    """
    Remove model:/[server: banner lines and blank lines; return the rest.
    """
    lines = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("model:"):
            continue
        if s.startswith("[server:"):
            continue
        lines.append(s)
    return "\n".join(lines)


def _retry_hint(kind):
    return (
        WATCHDOG_RETRY_HINT_OWRAP_F if kind in _TASKLIKE_KINDS
        else WATCHDOG_RETRY_HINT_FILE_TASK
    )


class Watchdog:
    """Monitor a log file for staleness and invoke callbacks on stall/kill.

    Owns kind/sentinel_path/url and its own has_output/model_logged state,
    so it can classify and report a stall/kill/unresponsive event itself —
    callers only need to supply the mechanics of stopping the process.
    """

    def __init__(self, log_path, kind, sentinel_path, url, kill_callback,
                 kill_after_s, notify_callback=None, stall_s=None,
                 poll_s=None, no_output_s=None, infra_failure_s=None,
                 unresponsive_callback=None):
        _cfg = _read_config()
        self._log_path = Path(log_path)
        self._kind = kind
        self._sentinel_path = sentinel_path
        self._url = url
        self._kill_callback = kill_callback
        self._notify_callback = notify_callback
        self._kill_after_s = kill_after_s
        self._stall_s = stall_s if stall_s is not None else float(
            _cfg.get("stall_notify_s", STALL_NOTIFY_S)
        )
        self._poll_s = poll_s if poll_s is not None else float(
            _cfg.get("watchdog_poll_s", WATCHDOG_POLL_S)
        )
        self._script_stall_multiplier = float(
            _cfg.get("script_stall_multiplier", SCRIPT_STALL_MULTIPLIER)
        )
        self._thread = None
        self._stop_event = threading.Event()
        self._state = "healthy"
        self._stall_since = None
        self._last_mtime = 0
        self._last_size = 0
        self._last_change_time = time.time()
        self._no_output_s = no_output_s
        self._infra_failure_s = (
            infra_failure_s if infra_failure_s is not None else no_output_s
        )
        self._unresponsive_callback = unresponsive_callback
        self._no_output_fired = False
        self._has_output = False
        self._model_logged = False
        self._start_time = time.time()

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=self._poll_s + 1)

    def report_unresponsive(self):
        """
        No output at all (not even the model banner) — write health and
        print a kind-aware retry hint. Falls through to report_infra_failure
        if the model banner did appear.
        """
        if self._model_logged:
            self.report_infra_failure()
            return
        write_sentinel_health(self._sentinel_path, "unresponsive")
        elapsed_s = round(time.time() - self._start_time)
        rtlog.log(
            "watchdog.kill", kind=self._kind, reason="unresponsive",
            elapsed_s=elapsed_s, url=self._url,
        )
        msg = WATCHDOG_UNRESPONSIVE_MSG.format(retry_hint=_retry_hint(self._kind))
        if self._url:
            from .pool import record_unresponsive
            if record_unresponsive(self._url):
                msg += WATCHDOG_UNRESPONSIVE_EVICT_SUFFIX.format(url=self._url)
        print(msg, flush=True)

    def report_infra_failure(self):
        """
        Model banner appeared but nothing real followed — tell the
        caller to report this to the user and stop retrying.
        """
        write_sentinel_health(self._sentinel_path, "infra_failure")
        elapsed_s = round(time.time() - self._start_time)
        rtlog.log(
            "watchdog.kill", kind=self._kind, reason="infra_failure",
            elapsed_s=elapsed_s, url=self._url,
        )
        print(WATCHDOG_INFRA_FAILURE_MSG, flush=True)

    def report_kill(self):
        """
        Generic stall/kill path — classify as a real stall, an infra
        failure, or unresponsive, using this watchdog's own state.
        """
        if self._has_output:
            elapsed_s = round(time.time() - self._start_time)
            rtlog.log(
                "watchdog.kill", kind=self._kind, reason="stalled",
                elapsed_s=elapsed_s, url=self._url,
            )
            print(WATCHDOG_KILL_STALL_MSG.format(kind=self._kind), flush=True)
        else:
            self.report_unresponsive()

    def check_output(self):
        """
        Read the log, update _has_output/_model_logged if not already
        set. Safe to call multiple times — a no-op once _has_output is
        True.
        """
        if self._has_output:
            return
        try:
            content = self._log_path.read_text()
        except OSError:
            content = ""
        idx = content.find("EXECUTOR OUTPUT")
        if idx != -1:
            nl = content.find("\n", idx)
            content = content[nl + 1:] if nl != -1 else ""
        else:
            content = ""
        if not self._model_logged and re.search(r'(?m)^model:', content):
            self._model_logged = True
        if strip_boilerplate(content):
            self._has_output = True

    def _notify(self, state):
        write_sentinel_health(self._sentinel_path, state)
        if self._notify_callback:
            self._notify_callback(state)
        else:
            print(f"[watchdog] {self._kind} {state}", flush=True)

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

    def _is_script_running(self):
        try:
            with open(self._log_path, 'rb') as f:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                f.seek(max(0, size - 4096))
                tail = f.read().decode('utf-8', errors='ignore')
        except OSError:
            return False
        lines = [l for l in tail.splitlines() if l.strip()]
        if not lines:
            return False
        last = lines[-1]
        return (
            bool(_SCRIPT_TRIGGER_RE.search(last))
            and bool(_SCRIPT_WORD_RE.search(last))
        )

    def _is_write_running(self):
        """
        Check if the last log line indicates a large write or notebook execution.
        """
        try:
            with open(self._log_path, 'rb') as f:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                f.seek(max(0, size - 4096))
                tail = f.read().decode('utf-8', errors='ignore')
        except OSError:
            return False
        lines = [l for l in tail.splitlines() if l.strip()]
        if not lines:
            return False
        last = lines[-1]
        return (
            bool(_WRITE_TRIGGER_RE.search(last))
            and bool(_WRITE_TARGET_RE.search(last))
        )

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
                    self._notify("healthy")
            else:
                elapsed = now - self._last_change_time
                _scale = (
                    self._script_stall_multiplier
                    if self._is_script_running() or self._is_write_running()
                    else 1.0
                )
                if self._state == "healthy" and elapsed >= self._stall_s * _scale:
                    self._state = "stalled"
                    self._stall_since = now
                    self._notify("stalled")
                elif (
                    self._state == "stalled"
                    and self._stall_since
                    and now - self._stall_since >= self._kill_after_s * _scale
                ):
                    self.report_kill()
                    self._kill_callback()
                    break

            self.check_output()

            if self._no_output_s and not self._no_output_fired:
                deadline = (
                    self._infra_failure_s if self._model_logged
                    else self._no_output_s
                )
                if not self._has_output and (now - self._start_time) >= deadline:
                    self._no_output_fired = True
                    self.report_unresponsive()
                    if self._unresponsive_callback:
                        self._unresponsive_callback()
                    break
