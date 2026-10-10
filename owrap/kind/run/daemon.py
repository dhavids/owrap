import json
import os
import signal
import subprocess
import sys
import threading
import time

from . import Run
from ...dispatch.manager import Manager
from ...dispatch.process import is_alive
from ...session.resolver import _parse as _parse_session, session_files
from ...utils.dispatch.pool import (
    _active_load, _read_pool, ensure_min_servers, get_pool, shutdown_idle,
)
from ...utils.io.filelock import file_lock
from ...utils.log import rtlog
from ...utils.paths import (
    DAEMON_LOCK_FILE, DAEMON_PID_FILE, DAEMON_STATE_FILE, DOCS_DIR, OWRAP_ROOT,
    POOL_FILE, RECENTLY_DONE_DIR, RUNNING_DIR, SERVERS_DIR, SERVER_LOGS_DIR,
    SESSIONS_DIR, SESSION_DIR, STATS_FILE, _read_config,
)


def _kill_pid(pid: int, signum: int = 15) -> bool:
    """
    Send a signal to a process and report whether it succeeded.
    """
    try:
        os.kill(pid, signum)
        return True
    except OSError:
        return False


def _wait_dead(pids: list, timeout: float = 3.0) -> None:
    """
    Wait up to `timeout` seconds for `pids` to exit, then SIGKILL any
    that remain.
    """
    deadline = time.time() + timeout
    remaining = list(pids)
    while remaining and time.time() < deadline:
        time.sleep(0.2)
        remaining = [p for p in remaining if is_alive(p)]
    for p in remaining:
        _kill_pid(p, 9)


def main():
    """
    Entry point for the owrap daemon process.
    """
    Daemon().run()


class Daemon(Run):
    """
    The background dispatch daemon: no stored record, just a process
    to start/stop/restart. Fully self-contained -- owns its own
    process management (PID file, lock, spawn/signal) directly,
    rather than calling into utils.dispatch.pool. `ensure_daemon` is
    the one static entry point for anything that needs to check/start
    the daemon without going through verb dispatch -- including the
    CLI's own watchdog tick (see `owrap/cli.py`), which calls it on
    every command so a daemon that died non-gracefully gets noticed
    and restarted on the next `owrap` invocation instead of staying
    dead indefinitely. `run` is the actual persistent loop body the
    spawned process executes -- pool lifecycle maintenance, plus
    each registered `WORKERS` entry's periodic check.
    """

    kind = "daemon"

    usage = {
        "start": {
            "usage": "", "args": [], "examples": [],
            "purpose": "Manage the background daemon process directly",
            "group": "server",
        },
        "stop": {
            "usage": "", "args": [], "examples": [],
            "purpose": "Manage the background daemon process directly",
            "group": "server",
        },
        "restart": {
            "usage": "", "args": [], "examples": [],
            "purpose": "Manage the background daemon process directly",
            "group": "server",
        },
        "get": {
            "usage": "", "args": [], "examples": [],
            "purpose": "Report whether the daemon is running (and its pid)",
            "group": "server",
        },
        "kill": {
            "usage": "[<session_id>]",
            "args": [("session_id", "only kill tasks scoped to this session")],
            "examples": ["", "abc123"],
            "purpose": "Kill all running tasks, pool servers, and the daemon "
                   "itself (optionally scoped to one session)",
            "group": "server",
        },
        "clean": {
            "usage": "[<session_id>]",
            "args": [("session_id", "only remove files whose id starts with this")],
            "examples": ["", "abc123"],
            "purpose": "Remove stale session/context/server-log files",
            "group": "server",
        },
    }

    messages = {
        "start": "{status}",
        "stop": "{status}",
        "restart": "{status}",
        "get": "daemon: running (pid {pid})",
        "kill": "{message}",
        "clean": "{message}",
    }

    TWO_HOURS = 2 * 3600

    # (name, enabled config key, interval config key, default interval_s,
    # check method name) -- each due, not-already-running entry gets its
    # check run in its own background thread so a slow one can't stall
    # the pool-lifecycle tick. Add a kind's own periodic check here (and
    # its `_check_<name>` method below) to move it into the daemon loop.
    WORKERS = (
        (
            "ctx", "owrap_context_manager_enabled", "ctx_check_interval_s",
            300.0, "_check_ctx",
        ),
    )


    # Public Methods

    def run(self) -> None:
        """
        Run the daemon loop for as long as the process lives. Exits
        immediately if the runner and every worker's config flag are
        all disabled -- nothing at all for the daemon to do.
        """
        config = _read_config()
        if not (
            config.get("owrap_runner_enabled", True)
            or any(config.get(key, True) for _, key, *_ in self.WORKERS)
        ):
            print("daemon: runner and all workers disabled, not starting")
            return

        my_pid = os.getpid()
        with file_lock(DAEMON_LOCK_FILE):
            existing_pid = Daemon._read_pid()
            if existing_pid is not None and existing_pid != my_pid:
                return
            DAEMON_PID_FILE.write_text(str(my_pid))

        daemon_start_file = DAEMON_STATE_FILE.with_name("daemon.start")
        try:
            if not daemon_start_file.exists():
                daemon_start_file.write_text(str(time.time()))
        except OSError:
            pass

        daemon_interval_s = float(config.get("daemon_interval_s", 10))
        idle_shutdown_s = float(config.get("idle_shutdown_s", 300))
        rtlog.log(
            "daemon.start", pid=my_pid, interval_s=daemon_interval_s,
            idle_shutdown_s=idle_shutdown_s,
        )
        last_run = {name: 0.0 for name, *_ in self.WORKERS}
        threads = {}
        idle_since = None
        prev_idle = None
        try:
            while True:
                try:
                    tick_config = _read_config()
                    self._run_due_workers(tick_config, last_run, threads)
                    idle_since, prev_idle = self._tick_pool(
                        tick_config, idle_shutdown_s, idle_since, prev_idle,
                    )
                    DAEMON_STATE_FILE.write_text(
                        json.dumps({"idle_since": idle_since}),
                    )
                except Exception:
                    pass
                time.sleep(daemon_interval_s)
        finally:
            rtlog.log("daemon.exit", pid=my_pid, reason="terminated")
            DAEMON_PID_FILE.unlink(missing_ok=True)
            DAEMON_STATE_FILE.unlink(missing_ok=True)
            daemon_start_file.unlink(missing_ok=True)


    # Private Methods

    def _default_get(self) -> None:
        """
        Report the daemon's own pid instead of raising the base
        Run's "does not support get" -- this is `get`'s whole meaning
        for a process kind with no stored items to index into.
        """
        with file_lock(DAEMON_LOCK_FILE):
            pid = Daemon._read_pid()
        if pid is None:
            self._fail("daemon: not running")
        self._ok("get", pid=pid)

    def _on_start(self) -> dict:
        started = Daemon.ensure_daemon()
        status = "daemon: started" if started else "daemon: already running"
        return {"status": status}

    def _on_stop(self, timeout: float = 3.0) -> dict:
        stopped = self._stop_process(timeout)
        status = "daemon: stopped" if stopped else "daemon: not running"
        return {"status": status}

    def _on_restart(self) -> dict:
        self._stop_process()
        Daemon.ensure_daemon()
        return {"status": "daemon: restarted"}

    def _on_kill(self, session_id: str = None) -> dict:
        """
        Kill every running task/server/daemon process (optionally
        scoped to `session_id`), and reset the dispatch stats file --
        ported from the old `KillServersRunner`.
        """
        killed_tasks, task_pids = self._kill_running_tasks(session_id)
        if task_pids:
            _wait_dead(task_pids)

        killed_servers, server_pids = self._kill_pool_servers()
        if server_pids:
            _wait_dead(server_pids)
        POOL_FILE.unlink(missing_ok=True)
        for f in SERVERS_DIR.glob("*.json") if SERVERS_DIR.exists() else ():
            f.unlink(missing_ok=True)

        killed_daemon = self._kill_daemon_process()
        self._reset_stats()

        parts = []
        if killed_tasks:
            parts.append(f"{killed_tasks} task{'s' if killed_tasks != 1 else ''}")
        if killed_servers:
            parts.append(f"{killed_servers} server{'s' if killed_servers != 1 else ''}")
        if killed_daemon:
            parts.append("daemon")
        message = f"killed {' and '.join(parts)}" if parts else "nothing running"
        return {"message": message}

    def _on_clean(self, session_id: str = None) -> dict:
        """
        Remove stale session files, orphaned context, and dead
        server/manager state (optionally scoped to `session_id`'s
        prefix) -- ported from the old `CleanupRunner`.
        """
        manager = Manager()
        state = manager._read_state()
        server_alive = False
        if state and state.get("pid"):
            server_alive = is_alive(state["pid"])

        removed = []
        if session_id:
            self._clean_matching_sessions(session_id, removed)
        else:
            self._clean_stale_sessions(removed)
            if not server_alive and state is not None:
                manager.stop()
                removed.append("manager.json (dead server state)")

        self._clean_orphan_context(removed)
        self._clean_server_logs(removed)
        self._clean_dead_server_json(removed)

        if removed:
            lines = [f"Cleaned up {len(removed)} item(s):"]
            lines.extend(f"  {name}" for name in removed)
            message = "\n".join(lines)
        else:
            status = "server alive" if server_alive else "server dead, nothing to remove"
            message = f"Nothing to clean up. ({status})"
        return {"message": message}

    def _stop_process(self, timeout: float = 3.0) -> bool:
        with file_lock(DAEMON_LOCK_FILE):
            pid = Daemon._read_pid()
            if pid is None:
                return False
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                DAEMON_PID_FILE.unlink(missing_ok=True)
                return False
            deadline = time.time() + timeout
            while time.time() < deadline:
                try:
                    os.kill(pid, 0)
                except OSError:
                    break
                time.sleep(0.1)
            else:
                try:
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass
            DAEMON_PID_FILE.unlink(missing_ok=True)
            return True

    def _run_due_workers(self, config: dict, last_run: dict, threads: dict) -> None:
        """
        Start each registered worker whose interval has elapsed and
        isn't already running, in its own background thread.
        """
        now = time.time()
        for name, enabled_key, interval_key, default_interval, check_name in (
            self.WORKERS
        ):
            if not config.get(enabled_key, True):
                continue
            interval_s = float(config.get(interval_key, default_interval))
            running = name in threads and threads[name].is_alive()
            if now - last_run[name] >= interval_s and not running:
                last_run[name] = now
                check = getattr(self, check_name)
                threads[name] = threading.Thread(target=check, daemon=True)
                threads[name].start()

    def _tick_pool(
        self, config: dict, idle_shutdown_s: float, idle_since, prev_idle,
    ) -> tuple:
        """
        Run one pool-lifecycle tick: shut down idle servers, maintain
        the minimum count if the runner is enabled, and log a
        `daemon.act` event when the pool size or idle state changes.
        Returns the (idle_since, prev_idle) pair for the next tick.
        """
        runner_enabled = config.get("owrap_runner_enabled", True)
        min_n = None if runner_enabled else 0
        pool = get_pool()
        before_n = len(pool)
        total_load = sum(_active_load(e["url"]) for e in pool)
        if total_load == 0:
            idle_since = idle_since or time.time()
        else:
            idle_since = None
        shutdown_idle(idle_s=idle_shutdown_s, min_n=min_n)
        if runner_enabled:
            ensure_min_servers()
        pool = get_pool()
        after_n = len(pool)
        after_load = sum(_active_load(e["url"]) for e in pool)
        started = max(0, after_n - before_n)
        killed = max(0, before_n - after_n)
        if started or killed or (idle_since is None) != (prev_idle is None):
            rtlog.log(
                "daemon.act", sid="daemon", killed=killed, started=started,
                pool_size=after_n, total_load=after_load,
            )
        return idle_since, idle_since

    def _check_ctx(self) -> None:
        """
        Run the background trigger check for every attached window,
        dispatching an Update Context / Update Protocol pass for any
        window whose transcript has grown since its last checkpoint.
        """
        from ...ctx.dispatch import check_all_attached
        check_all_attached()

    def _kill_running_tasks(self, session_id: str = None) -> tuple:
        killed, pids = 0, []
        if not RUNNING_DIR.exists():
            return killed, pids
        for sentinel in RUNNING_DIR.glob("*.json"):
            try:
                data = json.loads(sentinel.read_text())
                if session_id and data.get("session_id") != session_id:
                    continue
                pid = data.get("pid")
                if pid and is_alive(pid):
                    _kill_pid(pid)
                    pids.append(pid)
                    killed += 1
                data["rc"] = -9
                data["killed"] = True
                data["ended"] = time.time()
                RECENTLY_DONE_DIR.mkdir(parents=True, exist_ok=True)
                (RECENTLY_DONE_DIR / sentinel.name).write_text(json.dumps(data))
                sentinel.unlink(missing_ok=True)
            except Exception:
                sentinel.unlink(missing_ok=True)
        return killed, pids

    def _kill_pool_servers(self) -> tuple:
        killed, pids = 0, []
        for entry in _read_pool():
            pid = entry.get("pid")
            if pid and is_alive(pid):
                _kill_pid(pid)
                pids.append(pid)
                killed += 1
                rtlog.log(
                    "server.kill", pid=pid, port=entry.get("port"),
                    url=entry.get("url"), reason="killservers",
                )
        return killed, pids

    def _kill_daemon_process(self) -> bool:
        if not DAEMON_PID_FILE.exists():
            return False
        killed = False
        try:
            daemon_pid = int(DAEMON_PID_FILE.read_text().strip())
            if is_alive(daemon_pid):
                _kill_pid(daemon_pid)
                _wait_dead([daemon_pid])
                killed = True
        except (ValueError, OSError):
            pass
        DAEMON_PID_FILE.unlink(missing_ok=True)
        return killed

    def _reset_stats(self) -> None:
        STATS_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATS_FILE.write_text(json.dumps({
            "dispatched": 0, "succeeded": 0, "failed": 0,
            "stalled": 0, "timed_out": 0,
        }))

    def _clean_matching_sessions(self, session_id: str, removed: list) -> None:
        global_session = SESSION_DIR / "session"
        if SESSIONS_DIR.exists():
            for sf in session_files():
                data = _parse_session(sf)
                sid_val = data.get("session_id", "")
                if sid_val.startswith(session_id) or sf.stem.startswith(session_id):
                    sf.unlink(missing_ok=True)
                    removed.append(sf.name)
                    self._clean_context_files(data.get("session_id", sf.stem), removed)
        if global_session.exists():
            data = _parse_session(global_session)
            if data.get("session_id", "").startswith(session_id):
                global_session.unlink(missing_ok=True)
                removed.append("session (global)")
                self._clean_context_files(data.get("session_id", ""), removed)

    def _clean_stale_sessions(self, removed: list) -> None:
        now = time.time()
        global_session = SESSION_DIR / "session"
        if SESSIONS_DIR.exists():
            for sf in session_files():
                age = now - sf.stat().st_mtime
                is_ppid = sf.stem.isdigit()
                if age > self.TWO_HOURS or is_ppid:
                    sf.unlink(missing_ok=True)
                    data = _parse_session(sf)
                    removed.append(sf.name)
                    self._clean_context_files(data.get("session_id", sf.stem), removed)
        if global_session.exists():
            age = now - global_session.stat().st_mtime
            if age > self.TWO_HOURS:
                global_session.unlink(missing_ok=True)
                data = _parse_session(global_session)
                removed.append("session (global)")
                self._clean_context_files(data.get("session_id", ""), removed)

    def _clean_context_files(self, session_id: str, removed: list) -> None:
        for suffix in (".md", ".lock"):
            p = DOCS_DIR / f"context_{session_id}{suffix}"
            if p.exists():
                p.unlink(missing_ok=True)
                removed.append(f"context_{session_id}{suffix}")

    def _clean_orphan_context(self, removed: list) -> None:
        active_sids = set()
        if SESSIONS_DIR.exists():
            for sf in session_files():
                sid = _parse_session(sf).get("session_id", "").strip()
                if sid:
                    active_sids.add(sid)
        if not DOCS_DIR.exists():
            return
        for suffix in (".md", ".lock"):
            for f in DOCS_DIR.glob(f"context_*{suffix}"):
                sid = f.stem.replace("context_", "")
                if sid not in active_sids:
                    f.unlink(missing_ok=True)
                    removed.append(f.name)

    def _clean_server_logs(self, removed: list) -> None:
        for f in SERVER_LOGS_DIR.glob("owrap_start_*.log"):
            f.unlink(missing_ok=True)
            removed.append(f.name)
        for f in SERVER_LOGS_DIR.glob("owrap_*.log"):
            if f.name.startswith("owrap_start_"):
                continue
            try:
                os.kill(int(f.stem.replace("owrap_", "")), 0)
            except (ValueError, OSError):
                f.unlink(missing_ok=True)
                removed.append(f.name)

    def _clean_dead_server_json(self, removed: list) -> None:
        if not SERVERS_DIR.exists():
            return
        for f in SERVERS_DIR.glob("*.json"):
            try:
                pid = json.loads(f.read_text()).get("pid")
                if pid:
                    os.kill(pid, 0)
            except OSError:
                f.unlink(missing_ok=True)
                removed.append(f"servers/{f.name}")
            except Exception:
                pass


    # Static Methods

    @staticmethod
    def _read_pid() -> int:
        """
        Return the daemon's live pid from the pid file, cleaning up a
        stale file and returning None if it isn't actually running.
        Caller holds `DAEMON_LOCK_FILE`.
        """
        if not DAEMON_PID_FILE.exists():
            return None
        try:
            pid = int(DAEMON_PID_FILE.read_text().strip())
            os.kill(pid, 0)
            return pid
        except (ValueError, OSError):
            DAEMON_PID_FILE.unlink(missing_ok=True)
            return None

    @staticmethod
    def ensure_daemon() -> bool:
        """
        Start the daemon if it isn't already running and either the
        runner or context manager is enabled, returning whether a new
        daemon was actually spawned. Safe to call unconditionally
        (e.g. from the CLI's watchdog tick): a disabled config or an
        already-live daemon both make this a cheap no-op.
        """
        config = _read_config()
        if not (
            config.get("owrap_runner_enabled", True)
            or config.get("owrap_context_manager_enabled", True)
        ):
            return False
        with file_lock(DAEMON_LOCK_FILE):
            if Daemon._read_pid() is not None:
                return False
            proc = subprocess.Popen(
                [sys.executable, "-m", "owrap.kind.run.daemon"],
                start_new_session=True,
                cwd=str(OWRAP_ROOT),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            DAEMON_PID_FILE.write_text(str(proc.pid))
            return True


if __name__ == "__main__":
    main()
