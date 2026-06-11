import json
import os
import time
from pathlib import Path


def _kill_pid(pid: int, signum: int = 15) -> bool:
    try:
        os.kill(pid, signum)
        return True
    except OSError:
        return False


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _wait_dead(pids: list[int], timeout: float = 3.0):
    deadline = time.time() + timeout
    remaining = list(pids)
    while remaining and time.time() < deadline:
        time.sleep(0.2)
        remaining = [p for p in remaining if _pid_alive(p)]
    for p in remaining:
        _kill_pid(p, 9)


class KillServersRunner:
    def __init__(self, manager=None, logger=None, allow_all=False):
        pass

    def run(self, session_id: str | None = None):
        from ..utils.pool import POOL_FILE, _read_pool
        from ..utils.paths import SERVERS_DIR, RUNNING_DIR, RECENTLY_DONE_DIR

        killed_tasks = 0
        killed_servers = 0
        task_pids = []

        # Kill running tasks/exec/msg — read RUNNING_DIR sentinels
        if RUNNING_DIR.exists():
            for sentinel in RUNNING_DIR.glob("*.json"):
                try:
                    data = json.loads(sentinel.read_text())
                    # Filter by session_id if provided
                    if session_id and data.get("session_id") != session_id:
                        continue
                    pid = data.get("pid")
                    if pid and _pid_alive(pid):
                        _kill_pid(pid)
                        task_pids.append(pid)
                        killed_tasks += 1
                    # Mark sentinel as killed and move to recently_done
                    data["rc"] = -9
                    data["killed"] = True
                    data["ended"] = time.time()
                    RECENTLY_DONE_DIR.mkdir(parents=True, exist_ok=True)
                    (RECENTLY_DONE_DIR / sentinel.name).write_text(json.dumps(data))
                    sentinel.unlink(missing_ok=True)
                except Exception:
                    try:
                        sentinel.unlink(missing_ok=True)
                    except Exception:
                        pass

        # Wait for task processes to die, SIGKILL stragglers
        if task_pids:
            _wait_dead(task_pids)

        # Kill pool servers
        pool = _read_pool()
        server_pids = []
        for entry in pool:
            pid = entry.get("pid")
            if pid and _pid_alive(pid):
                _kill_pid(pid)
                server_pids.append(pid)
                killed_servers += 1

        if server_pids:
            _wait_dead(server_pids)

        # Clear pool.json and server state files
        try:
            POOL_FILE.unlink(missing_ok=True)
        except Exception:
            pass

        if SERVERS_DIR.exists():
            for f in SERVERS_DIR.glob("*.json"):
                try:
                    f.unlink()
                except Exception:
                    pass

        parts = []
        if killed_tasks:
            parts.append(f"{killed_tasks} task{'s' if killed_tasks != 1 else ''}")
        if killed_servers:
            parts.append(f"{killed_servers} server{'s' if killed_servers != 1 else ''}")
        if parts:
            print(f"killed {' and '.join(parts)}")
        else:
            print("nothing running")
