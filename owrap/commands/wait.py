import os
import sys
import time

from ..utils.paths import session_log, RUN_LOG, EXEC_LOG, READ_LOG
from ..base import BaseRunner


class WaitRunner(BaseRunner):

    def run(self, wait_type, wait_id=None, session_id=None, timeout=None):
        if session_id is None:
            session_id = os.environ.get("OWRAP_SESSION", "")
        if wait_type == "run":
            self._wait_any(session_log(RUN_LOG, session_id), timeout or 600, "10m")
        elif wait_type == "exec":
            self._wait_any(session_log(EXEC_LOG, session_id), timeout or 1800, "30m")
        elif wait_type == "read":
            if not wait_id:
                print("owait: read requires an id", file=sys.stderr)
                sys.exit(1)
            self._wait_marker(session_log(READ_LOG, session_id), f"[r:{wait_id}]", timeout or 300)
        elif wait_type == "msg":
            if not wait_id:
                print("owait: msg requires an id", file=sys.stderr)
                sys.exit(1)
            self._wait_marker(session_log(RUN_LOG, session_id), f"[m:{wait_id}]", timeout or 300)

    def _wait_any(self, log_path, timeout, label):
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.touch(exist_ok=True)
        initial_size = log_path.stat().st_size
        last_mtime = log_path.stat().st_mtime
        deadline = time.time() + timeout
        while time.time() < deadline:
            if log_path.exists():
                mtime = log_path.stat().st_mtime
                if mtime != last_mtime:
                    last_mtime = mtime
                    if log_path.stat().st_size > initial_size:
                        lines = [l for l in log_path.read_text().splitlines()
                                 if l.strip() and l[0].isdigit()]
                        if lines:
                            print(lines[0])
                            sys.exit(0)
            time.sleep(0.2)
        print(f"owait: timed out after {label}", file=sys.stderr)
        sys.exit(1)

    def _wait_marker(self, log_path, marker, timeout):
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.touch(exist_ok=True)
        last_mtime = 0
        deadline = time.time() + timeout
        while time.time() < deadline:
            if log_path.exists():
                mtime = log_path.stat().st_mtime
                if mtime != last_mtime:
                    last_mtime = mtime
                    if marker in log_path.read_text():
                        sys.exit(0)
            time.sleep(0.2)
        print(f"owait: timed out waiting for {marker}", file=sys.stderr)
        sys.exit(1)
