import json
import os
import signal
import sys
import time
from abc import ABC, abstractmethod
from typing import Optional


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
        """Return the server URL from the manager, or None."""
        return self.manager.get_server_url()

    def _write_sentinel(self, task_id, title, kind="task"):
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
            "title": title,
            "started": time.time(),
            "server_url": self._get_server_url() or "",
        }
        path = RUNNING_DIR / name
        path.write_text(json.dumps(data))
        return path

    def _complete_sentinel(self, sentinel_path, rc, timed_out=False):
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
            (RECENTLY_DONE_DIR / sentinel_path.name).write_text(json.dumps(data))
            sentinel_path.unlink()
        except Exception:
            pass

    def _install_sigterm_handler(self):
        def _handler(signum, frame):
            sys.exit(143)
        signal.signal(signal.SIGTERM, _handler)

    def _cleanup_recently_done(self):
        from .utils.paths import RUNNING_DIR, RECENTLY_DONE_DIR
        # Reap stale running sentinels whose PID is dead
        if RUNNING_DIR.exists():
            for f in RUNNING_DIR.iterdir():
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
                    if not alive:
                        RECENTLY_DONE_DIR.mkdir(parents=True, exist_ok=True)
                        data["finished"] = time.time()
                        data["rc"] = 143
                        data["crashed"] = True
                        (RECENTLY_DONE_DIR / f.name).write_text(json.dumps(data))
                        f.unlink()
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
