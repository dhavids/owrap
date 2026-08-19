import json
import os
import signal
import sys
import tempfile
import time
from abc import ABC, abstractmethod
from typing import Optional

from .utils import rtlog


def _increment_stat(key: str):
    """Atomically increment a counter in the stats file using flock."""
    import fcntl
    from .utils.paths import STATS_FILE
    STATS_FILE.parent.mkdir(parents=True, exist_ok=True)
    lock_path = STATS_FILE.with_suffix(".lock")
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            data = json.loads(STATS_FILE.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            data = {
                "dispatched": 0, "succeeded": 0, "failed": 0,
                "stalled": 0, "timed_out": 0,
            }
        data[key] = data.get(key, 0) + 1
        STATS_FILE.write_text(json.dumps(data))
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


class BaseRunner(ABC):
    """Abstract base for owrap subcommand runners."""

    def __init__(self, manager, logger=None, allow_all=False):
        self.manager = manager
        self.logger = logger
        self.allow_all = allow_all

    @abstractmethod
    def run(self, args) -> int:
        """Execute the runner's subcommand. Returns exit code."""
        ...

    def _get_server_url(self) -> Optional[str]:
        return self.manager.get_server_url()

    def _write_sentinel(
        self, task_id, title, kind="task", call_type="task",
        url=None, output_path=None,
    ):
        from .utils.paths import RUNNING_DIR
        RUNNING_DIR.mkdir(parents=True, exist_ok=True)
        session_id = self.manager.session_id or "none"
        research = self.manager.research or "none"
        name = f"{kind}{task_id}_{session_id}.json"
        data = {
            "pid": os.getpid(),
            "task_id": str(task_id),
            "session_id": session_id,
            "research": research,
            "kind": kind,
            "call_type": call_type,
            "title": title,
            "started": time.time(),
            "server_url": url or self._get_server_url() or "",
            "output_path": str(output_path) if output_path else "",
        }
        path = RUNNING_DIR / name
        fd, tmp_path = tempfile.mkstemp(
            dir=str(RUNNING_DIR), prefix=f".{name}.", suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w") as f:
                f.write(json.dumps(data))
            os.replace(tmp_path, path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        rtlog.log(
            "dispatch.start", kind=kind, label=title, url=data["server_url"],
            task_id=str(task_id),
        )
        return path

    def _complete_sentinel(
        self, sentinel_path, rc, timed_out=False, stalled=False,
        failure_kind=None, raw_rc=None,
    ):
        if getattr(self, '_externally_killed', False):
            return
        from .utils.paths import RECENTLY_DONE_DIR
        if sentinel_path is None or not sentinel_path.exists():
            return
        try:
            RECENTLY_DONE_DIR.mkdir(parents=True, exist_ok=True)
            data = json.loads(sentinel_path.read_text())
            data["finished"] = time.time()
            data["rc"] = rc
            if timed_out:
                data["timed_out"] = True
            if failure_kind:
                data["failure_kind"] = failure_kind
            if raw_rc is not None and raw_rc != rc:
                data["raw_rc"] = raw_rc
            done_name = sentinel_path.name
            done_path = RECENTLY_DONE_DIR / done_name
            fd, tmp_path = tempfile.mkstemp(
                dir=str(RECENTLY_DONE_DIR), prefix=f".{done_name}.",
                suffix=".tmp",
            )
            try:
                with os.fdopen(fd, "w") as f:
                    f.write(json.dumps(data))
                os.replace(tmp_path, done_path)
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
            sentinel_path.unlink()
        except Exception:
            pass

        _increment_stat("dispatched")
        if rc == 0:
            _increment_stat("succeeded")
        elif timed_out:
            _increment_stat("timed_out")
        elif stalled:
            _increment_stat("stalled")
        else:
            _increment_stat("failed")

    def _finish_dispatch(
        self, label, result, watchdog, sentinel_path, log_path,
        timeout_s, default_timeout_s,
    ):
        """
        Normalize timeout, infra-failure, and rc handling, then write the
        RESULT footer and completion sentinel. Returns the final rc.
        """
        from datetime import datetime
        from .utils.snippet import divider

        timed_out = bool(result.get("timed_out"))
        stall_killed = getattr(self, '_stall_killed', False)
        raw_rc = result.get("returncode", 1)
        failure_kind = None

        if timed_out:
            partial = (result.get("stdout") or "").strip()
            print(flush=True)
            print(
                f"[{label}] timed out after {timeout_s:.0f}s "
                f"({len(partial)} chars captured)",
                flush=True,
            )
            print(
                f"  rerun with -t <seconds> to extend "
                f"(default: {default_timeout_s}s)",
                flush=True,
            )
            rc = 2
            failure_kind = "timeout"
        elif stall_killed:
            rc = raw_rc
            if watchdog is not None and not watchdog._has_output:
                if watchdog._model_logged:
                    rc = 1
                    failure_kind = "infra_failure"
                else:
                    rc = 4
                    failure_kind = "unresponsive"
            else:
                failure_kind = "stalled"
        else:
            rc = raw_rc
            if rc == 0 and watchdog is not None:
                watchdog.check_output()
                if not watchdog._has_output:
                    if watchdog._model_logged:
                        rc = 1
                        failure_kind = "infra_failure"
                        watchdog.report_infra_failure()
                    else:
                        rc = 4
                        failure_kind = "unresponsive"
                        watchdog.report_unresponsive()
            elif rc != 0:
                rc = 3
                failure_kind = "crashed"

        if rc == 0:
            _reason = "ok"
        elif failure_kind == "crashed":
            _reason = f"crashed (exit {raw_rc})"
        elif failure_kind:
            _reason = failure_kind.replace("_", " ")
        else:
            _reason = f"rc={rc}"
        try:
            with open(log_path, "a") as _lf:
                _lf.write(
                    f"\n{divider('RESULT')}\n"
                    f"[{datetime.now().isoformat()}] rc={rc} {_reason}\n"
                )
        except Exception:
            pass

        self._complete_sentinel(
            sentinel_path, rc, timed_out=timed_out, stalled=stall_killed,
            failure_kind=failure_kind, raw_rc=raw_rc,
        )
        rtlog.log(
            "dispatch.end", label=label, rc=rc, raw_rc=raw_rc,
            failure_kind=failure_kind, timed_out=timed_out,
        )
        return rc

    def _install_sigterm_handler(self):
        def _handler(signum, frame):
            self._externally_killed = True
            sys.exit(143)
        signal.signal(signal.SIGTERM, _handler)

    def _cleanup_recently_done(self):
        from .utils.paths import RUNNING_DIR, RECENTLY_DONE_DIR


        # Reap stale running sentinels whose PID is dead

        if RUNNING_DIR.exists():
            running_entries = list(RUNNING_DIR.iterdir())
            for f in running_entries:
                try:
                    data = json.loads(f.read_text())
                    pid = data.get("pid")
                    alive = False
                    if pid:
                        try:
                            os.kill(pid, 0)
                            alive = True
                        except OSError:
                            pass
                    recent = (time.time() - f.stat().st_mtime) < 5
                    if not alive and recent:
                        continue  # grace period, may still be completing
                    if not alive:
                        RECENTLY_DONE_DIR.mkdir(parents=True, exist_ok=True)
                        done_path = RECENTLY_DONE_DIR / f.name
                        if done_path.exists():
                            f.unlink()  # already completed, don't clobber
                            continue
                        data["finished"] = time.time()
                        data["rc"] = 143
                        data["failure_kind"] = "reaped"
                        done_path.write_text(json.dumps(data))
                        f.unlink()
                        age_s = round(time.time() - data.get("started", time.time()))
                        rtlog.log(
                            "dispatch.reap", task_id=data.get("task_id"),
                            age_s=age_s,
                        )
                except Exception:
                    pass


        # Remove recently_done entries older than 120s

        if not RECENTLY_DONE_DIR.exists():
            return
        cutoff = time.time() - 120
        for f in RECENTLY_DONE_DIR.iterdir():
            try:
                data = json.loads(f.read_text())
                if data.get("finished", 0) < cutoff:
                    f.unlink()
            except Exception:
                pass
