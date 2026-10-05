import json
import os
import re
import time
from pathlib import Path

SERVER_LOG_KEEP = 10
STARTUP_LOG_GRACE_S = 60


def _live_server_pids(home: Path) -> set[int]:
    pids = set()
    state_files = [home / "runtime" / "manager.json"]
    state_files.extend((home / "servers").glob("*.json"))

    for path in state_files:
        try:
            data = json.loads(path.read_text())
            if not isinstance(data, dict):
                continue
            pid = int(data.get("pid", 0))
            if pid > 0:
                os.kill(pid, 0)
                pids.add(pid)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue

    try:
        pool = json.loads((home / "runtime" / "pool.json").read_text())
        if not isinstance(pool, list):
            pool = []
        for entry in pool:
            try:
                if not isinstance(entry, dict):
                    continue
                pid = int(entry.get("pid", 0))
                if pid > 0:
                    os.kill(pid, 0)
                    pids.add(pid)
            except (OSError, ValueError, TypeError):
                continue
    except (OSError, TypeError, json.JSONDecodeError):
        pass
    return pids


def prune_server_logs(home: Path, log_dir: Path) -> None:
    """
    Keep recent server logs and active server or startup logs.
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    now = time.time()
    active_pids = _live_server_pids(home)
    candidates = []
    protected = set()

    for path in log_dir.glob("owrap_*.log"):
        match = re.fullmatch(r"owrap_(\d+)\.log", path.name)
        startup = path.name.startswith("owrap_start_")
        if not (match or startup):
            continue
        try:
            modified = path.stat().st_mtime
        except OSError:
            continue
        candidates.append((modified, path))
        if match and int(match.group(1)) in active_pids:
            protected.add(path)
        if startup and now - modified < STARTUP_LOG_GRACE_S:
            protected.add(path)

    keep = set(protected)
    for _, path in sorted(candidates, reverse=True):
        if len(keep) >= SERVER_LOG_KEEP:
            break
        keep.add(path)
    for _, path in candidates:
        if path not in keep:
            path.unlink(missing_ok=True)

    for path in home.glob("owrap_start_*.log"):
        try:
            if now - path.stat().st_mtime >= STARTUP_LOG_GRACE_S:
                path.unlink(missing_ok=True)
        except OSError:
            continue
