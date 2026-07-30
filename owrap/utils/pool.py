import fcntl
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

from .paths import (
    _read_config, SERVERS_DIR, RUNNING_DIR,
    KEEPALIVE_PID_FILE, POOL_FILE, POOL_LOCK_FILE,
)

MIN_SERVERS = 2


def _read_pool() -> list[dict]:
    try:
        if POOL_FILE.exists():
            with open(POOL_FILE) as f:
                return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return []


def _write_pool(pool: list[dict]):
    POOL_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(POOL_FILE.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(pool, f)
        os.rename(tmp_path, str(POOL_FILE))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


@contextmanager
def _pool_lock():
    POOL_LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(POOL_LOCK_FILE), os.O_CREAT | os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _is_alive(pid) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _is_responsive(url) -> bool:
    import socket
    try:
        addr = url.replace("http://", "").replace("https://", "")
        parts = addr.rsplit(":", 1)
        host = parts[0]
        port = int(parts[1]) if len(parts) > 1 else 4096
        with socket.create_connection((host, port), timeout=1):
            return True
    except (OSError, ValueError):
        return False


def _start_server(port: int) -> dict:
    from ..manager import Manager
    m = Manager(port=port)
    url = m.start(port=port)
    state = m._read_state() or {}
    pid = state.get("pid")
    if pid is None:
        raise RuntimeError("server started but pid not found in state")
    return {"port": port, "url": url, "pid": pid, "last_used": time.time()}


def _next_port(pool: list) -> int:
    """Scan the current pool for used ports and return the next free port
    in the configured range.
    """
    config = _read_config()
    max_servers = int(config.get("max_servers", 5))
    used = {entry.get("port") for entry in pool}
    for p in range(4096, 4096 + max_servers):
        if p not in used:
            return p
    raise RuntimeError("no available ports in pool range")


def _pool_active() -> bool:
    """Return True when pool mode is active (max_servers >= min_servers)."""
    config = _read_config()
    max_servers = int(config.get("max_servers", 1))
    min_servers = int(config.get("min_servers", MIN_SERVERS))
    return max_servers >= min_servers


def get_pool() -> list[dict]:
    """Remove unreachable or stale pool entries whose PID is no longer alive."""
    with _pool_lock():
        pool = _read_pool()
        live = []
        for entry in pool:
            pid = entry.get("pid")
            if pid and _is_alive(pid) and _is_responsive(entry.get("url", "")):
                live.append(entry)
        if len(live) != len(pool):
            _write_pool(live)
        return live


def ensure_min_servers():
    """Start servers until pool reaches min_servers; no-op if already
    at or above minimum.
    """
    with _pool_lock():
        pool = _read_pool()
        config = _read_config()
        min_servers = int(config.get("min_servers", MIN_SERVERS))
        max_servers = int(config.get("max_servers", 5))
        live = [
            entry for entry in pool
            if entry.get("pid")
            and _is_alive(entry["pid"])
            and _is_responsive(entry.get("url", ""))
        ]
        while len(live) < min_servers and len(live) < max_servers:
            try:
                port = _next_port(live)
                entry = _start_server(port)
                live.append(entry)
            except RuntimeError:
                break
        _write_pool(live)



def _wait_responsive(url: str, timeout: float = 5.0):
    """Block until the server at url is accepting connections (or timeout)."""
    deadline = time.time() + timeout
    while not _is_responsive(url) and time.time() < deadline:
        time.sleep(0.1)


def pick_server(call_type: str) -> str:
    """Select the best available server from the pool for the given call type.

    Routes work to the least-loaded live server, starts new servers when
    needed, and reaps draining or unresponsive entries.
    """
    if not _pool_active():
        raise RuntimeError("pool is not active")
    _ensure_keepalive()  # self-heals keepalive on every pooled dispatch
    ensure_min_servers()
    with _pool_lock():
        pool = _read_pool()
        live = [
            entry for entry in pool
            if entry.get("pid")
            and _is_alive(entry["pid"])
            and _is_responsive(entry.get("url", ""))
        ]
        config = _read_config()
        max_servers = int(config.get("max_servers", 5))
        max_req = int(config.get("max_requests", 0))

        # Mark any server that has hit its request quota as draining: stop routing new
        # work to it, but let in-flight requests finish rather than killing it outright
        # (killing only when idle avoids cutting off a live request).
        if max_req > 0:
            for e in live:
                if e.get("request_count", 0) >= max_req:
                    e["draining"] = True

        # Reap draining servers once they've gone idle.
        exhausted = [
            e for e in live
            if e.get("draining") and _active_load(e.get("url", "")) == 0 and e.get("reserved", 0) == 0
        ]
        for e in exhausted:
            pid = e.get("pid")
            if pid:
                try:
                    os.kill(pid, 15)
                except OSError:
                    pass
        live = [e for e in live if e not in exhausted]

        if not live:
            # Entries here failed the liveness/responsiveness check above but may still be
            # actually running (hung, not dead) — force-kill them so they don't leak as
            # untracked orphans once the pool below is overwritten.
            for stale in pool:
                pid = stale.get("pid")
                if not pid or not _is_alive(pid):
                    continue
                try:
                    os.kill(pid, 15)
                except OSError:
                    pass
                deadline = time.time() + 2.0
                while _is_alive(pid) and time.time() < deadline:
                    time.sleep(0.1)
                if _is_alive(pid):
                    try:
                        os.kill(pid, 9)
                    except OSError:
                        pass
            port = _next_port(exhausted)
            entry = _start_server(port)
            _wait_responsive(entry["url"])
            _write_pool([entry])
            return entry["url"]

        # Draining servers stay tracked in the pool (so they can still be reaped once
        # idle) but are never selected for new work.
        selectable = [e for e in live if not e.get("draining")]
        if not selectable:
            # Every live server is draining (still finishing in-flight work) — start a
            # fresh one so new work has somewhere to go, even if this briefly exceeds
            # max_servers; the draining entries will be reaped as they go idle.
            port = _next_port(live)
            entry = _start_server(port)
            _wait_responsive(entry["url"])
            _write_pool(live + [entry])
            return entry["url"]

        # compute load per server (active + reserved)
        now = time.time()
        loads = {
            entry["url"]: _active_load(entry["url"]) + entry.get("reserved", 0)
            for entry in selectable
        }
        zero_load = [entry for entry in selectable if loads[entry["url"]] == 0]
        if zero_load:
            warm = [e for e in zero_load if now - e.get("last_used", 0) < 30]
            if warm:
                best = min(warm, key=lambda e: now - e.get("last_used", 0))
            else:
                best = min(zero_load, key=lambda e: now - e.get("last_used", 0))
        elif len(live) < max_servers:
            port = _next_port(live)
            entry = _start_server(port)
            _wait_responsive(entry["url"])
            _write_pool(live + [entry])
            return entry["url"]
        else:
            estimates = {
                entry["url"]: _estimate_remaining(entry["url"], now)
                for entry in selectable
            }
            if call_type in ("msg", "read", "agent"):
                for entry in selectable:
                    tasks = _active_tasks_by_type(entry["url"])
                    exec_count = tasks.get("exec", 0)
                    estimates[entry["url"]] += exec_count * 30
            best = min(selectable, key=lambda e: estimates[e["url"]])
        best["last_used"] = time.time()
        best["reserved"] = best.get("reserved", 0) + 1
        best["request_count"] = best.get("request_count", 0) + 1
        _write_pool(live)
        return best["url"]


def update_last_used(url: str):
    """Update last_used timestamp for a pool entry; used by load balancer
    warm-server preference.
    """
    with _pool_lock():
        pool = _read_pool()
        for entry in pool:
            if entry.get("url") == url:
                entry["last_used"] = time.time()
                break
        _write_pool(pool)


def release_server(url: str):
    """Decrement the in-flight task counter for a pool entry after a
    dispatch completes.
    """
    with _pool_lock():
        pool = _read_pool()
        for entry in pool:
            if entry.get("url") == url:
                entry["reserved"] = max(0, entry.get("reserved", 0) - 1)
                break
        _write_pool(pool)


def record_unresponsive(url: str, threshold: int | None = None) -> bool:
    """Increment a server's consecutive-unresponsive counter. Once it
    reaches `threshold` (config key 'unresponsive_kill_threshold',
    default UNRESPONSIVE_KILL_THRESHOLD), mark that server as draining
    so pick_server() stops routing new work to it — actual eviction
    happens once it goes idle, via the same draining-reap logic
    pick_server already uses for the max_requests quota case, so an
    in-flight request on it (from a different concurrent dispatch)
    isn't cut off. Returns True if the server was newly marked
    draining, False otherwise.
    """
    from ..constants import UNRESPONSIVE_KILL_THRESHOLD
    if threshold is None:
        threshold = int(
            _read_config().get("unresponsive_kill_threshold", UNRESPONSIVE_KILL_THRESHOLD)
        )
    with _pool_lock():
        pool = _read_pool()
        marked = False
        for entry in pool:
            if entry.get("url") == url:
                entry["unresponsive_count"] = entry.get("unresponsive_count", 0) + 1
                if entry["unresponsive_count"] >= threshold and not entry.get("draining"):
                    entry["draining"] = True
                    marked = True
                break
        _write_pool(pool)
        return marked


def record_responsive(url: str):
    """Reset a server's unresponsive counter after a dispatch that
    actually produced output.
    """
    with _pool_lock():
        pool = _read_pool()
        for entry in pool:
            if entry.get("url") == url:
                entry["unresponsive_count"] = 0
                break
        _write_pool(pool)


def shutdown_idle(idle_s: float | None = None, min_n: int | None = None):
    """Kill servers idle beyond idle_s seconds, keeping at least min_n alive."""
    config = _read_config()
    if idle_s is None:
        idle_s = float(config.get("idle_shutdown_s", 600))
    if min_n is None:
        min_n = int(config.get("min_servers", MIN_SERVERS))
    with _pool_lock():
        pool = _read_pool()
        live = [
            entry for entry in pool
            if entry.get("pid")
            and _is_alive(entry["pid"])
            and _is_responsive(entry.get("url", ""))
        ]
        now = time.time()
        # Heal stale reservations: reserved > 0 but no active tasks
        # means a crash leaked the counter. Only heal if the reservation
        # is older than a small grace period, avoiding the race window
        # where reserved was just incremented but the sentinel file
        # hasn't been written yet.
        _RESERVED_HEAL_GRACE = 5.0
        for entry in live:
            if (entry.get("reserved", 0) > 0
                    and _active_load(entry["url"]) == 0
                    and (now - entry.get("last_used", now)) > _RESERVED_HEAL_GRACE):
                entry["reserved"] = 0
        _write_pool(live)
        to_keep = []
        killed = 0
        for entry in live:
            if entry.get("reserved", 0) > 0:
                to_keep.append(entry)
                continue
            elapsed = now - entry.get("last_used", 0)
            should_kill = elapsed > idle_s and (len(live) - killed) > min_n
            if should_kill:
                try:
                    pid = entry["pid"]
                    os.kill(pid, 15)
                    port = entry.get("port")
                    if port:
                        state_file = SERVERS_DIR / f"{port}.json"
                        try:
                            state_file.unlink(missing_ok=True)
                        except OSError:
                            pass
                    killed += 1
                except OSError:
                    pass
            else:
                to_keep.append(entry)
        _write_pool(to_keep)


def _active_load(url: str) -> int:
    """Count currently active (alive PID) tasks routed to the given
    server URL by call type.
    """
    count = 0
    if not RUNNING_DIR.exists():
        return 0
    for f in RUNNING_DIR.glob("*.json"):
        try:
            data = json.loads(f.read_text())
            if data.get("server_url") == url:
                pid = data.get("pid")
                if pid:
                    try:
                        os.kill(pid, 0)
                        count += 1
                    except OSError:
                        pass
        except Exception:
            pass
    return count


def _active_tasks_by_type(url: str) -> dict[str, int]:
    counts = {}
    if not RUNNING_DIR.exists():
        return counts
    for f in RUNNING_DIR.glob("*.json"):
        try:
            data = json.loads(f.read_text())
            if data.get("server_url") == url:
                pid = data.get("pid")
                if pid:
                    try:
                        os.kill(pid, 0)
                        call_type = data.get("call_type", "task")
                        counts[call_type] = counts.get(call_type, 0) + 1
                    except OSError:
                        pass
        except Exception:
            pass
    return counts


def _estimate_remaining(url: str, now: float | None = None) -> float:
    """Sum estimated remaining seconds across all active tasks on the given server URL."""
    if now is None:
        now = time.time()
    from ..constants import EXPECTED_DURATION_S
    from .paths import _read_config as _rc
    total = 0.0
    if not RUNNING_DIR.exists():
        return total
    for f in RUNNING_DIR.glob("*.json"):
        try:
            data = json.loads(f.read_text())
            if data.get("server_url") == url:
                pid = data.get("pid")
                if pid:
                    try:
                        os.kill(pid, 0)
                        call_type = data.get("call_type", "task")
                        started = data.get("started", now)
                        _cfg_dur = _rc()
                        duration = float(
                            _cfg_dur.get(
                                f"expected_duration_{call_type}",
                                EXPECTED_DURATION_S.get(call_type, 6),
                            )
                        )
                        remaining = max(0.0, duration - (now - started))
                        total += remaining
                    except OSError:
                        pass
        except Exception:
            pass
    return total


def _ensure_keepalive():
    keepalive_pid_file = KEEPALIVE_PID_FILE
    owrap_dir = Path.home() / "marl" / "owrap"
    if keepalive_pid_file.exists():
        try:
            pid = int(keepalive_pid_file.read_text().strip())
            os.kill(pid, 0)
            return
        except (ValueError, OSError):
            pass
    # start keepalive
    proc = subprocess.Popen(
        ["owrap", "keepalive"],
        start_new_session=True,
        cwd=str(owrap_dir) if owrap_dir.exists() else None,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    keepalive_pid_file.write_text(str(proc.pid))
