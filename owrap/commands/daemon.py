import os
import sys
import threading
import time
from pathlib import Path

from ..base import BaseRunner
from ..utils.dispatch.pool import (
    get_pool, _active_load, shutdown_idle, ensure_min_servers,
)
from ..utils.paths import _read_config
from ..utils.log import rtlog


def main():
    """
    Entry point for the owrap daemon process.
    """
    from ..manager import Manager
    manager = Manager()
    DaemonRunner(manager).run()


class DaemonRunner(BaseRunner):
    """
    Persistent background process, serving two independently-gated jobs:
    pool lifecycle management (shuts down idle servers, maintains minimum
    server count — needs `owrap_runner_enabled`, since that's the dispatch
    tooling the pool exists for) and context-manager background work
    (needs `owrap_context_manager_enabled`). Stays running regardless of
    pool load as long as either is enabled — it does not exit itself once
    started.
    """
    def run(self):
        """
        Run the daemon loop for as long as the process lives.

        Exits immediately without starting the loop if both
        `owrap_runner_enabled` and `owrap_context_manager_enabled` are
        false — nothing at all for the daemon to do in that case.
        """
        config = _read_config()
        if not (
            config.get("owrap_runner_enabled", True)
            or config.get("owrap_context_manager_enabled", True)
        ):
            print("daemon: runner and context manager both disabled, not starting")
            sys.exit(0)

        from ..utils.paths import DAEMON_PID_FILE, DAEMON_STATE_FILE
        daemon_pid_file = DAEMON_PID_FILE
        my_pid = os.getpid()
        try:
            import subprocess as _sp
            result = _sp.run(
                ["pgrep", "-f", "owrap.runner daemon"],
                capture_output=True, text=True
            )
            for _pid_str in result.stdout.strip().splitlines():
                try:
                    _sib = int(_pid_str)
                    if _sib != my_pid:
                        os.kill(_sib, 15)
                except (ValueError, OSError):
                    pass
        except Exception:
            pass
        daemon_pid_file.write_text(str(my_pid))

        daemon_start_file = DAEMON_STATE_FILE.with_name("daemon.start")
        try:
            if not daemon_start_file.exists():
                daemon_start_file.write_text(str(time.time()))
        except Exception:
            pass

        config = _read_config()
        idle_shutdown_s = float(config.get("idle_shutdown_s", 300))
        daemon_interval_s = float(config.get("daemon_interval_s", 10))
        ctx_check_interval_s = float(config.get("ctx_check_interval_s", 300))
        daemon_state_file = DAEMON_STATE_FILE
        idle_since = None
        last_ctx_check = 0.0
        rtlog.log(
            "daemon.start", pid=my_pid, interval_s=daemon_interval_s,
            idle_shutdown_s=idle_shutdown_s,
        )
        import json as _json
        prev_idle = None
        ctx_check_thread = None
        try:
            while True:
                try:
                    tick_config = _read_config()
                    if tick_config.get("owrap_context_manager_enabled", True):
                        now = time.time()
                        due = now - last_ctx_check >= ctx_check_interval_s
                        running = (
                            ctx_check_thread is not None
                            and ctx_check_thread.is_alive()
                        )
                        if due and not running:
                            last_ctx_check = now
                            from .context_manager import CtxWorkerRunner
                            # Backgrounded so a slow dispatch can't stall pool checks.
                            ctx_check_thread = threading.Thread(
                                target=CtxWorkerRunner().check_all_attached,
                                daemon=True,
                            )
                            ctx_check_thread.start()

                    if tick_config.get("owrap_runner_enabled", True):
                        pool = get_pool()
                        before_n = len(pool)
                        total_load = sum(_active_load(e["url"]) for e in pool)
                        if total_load == 0:
                            if idle_since is None:
                                idle_since = time.time()
                            shutdown_idle(idle_s=idle_shutdown_s)
                        else:
                            idle_since = None
                            shutdown_idle(idle_s=idle_shutdown_s)
                        ensure_min_servers()
                        pool = get_pool()
                        after_n = len(pool)
                        after_load = sum(_active_load(e["url"]) for e in pool)
                        started = max(0, after_n - before_n)
                        killed = max(0, before_n - after_n)
                        idle_changed = (idle_since is None) != (prev_idle is None)
                        if started or killed or idle_changed:
                            rtlog.log(
                                "daemon.act", sid="daemon", killed=killed,
                                started=started, pool_size=after_n,
                                total_load=after_load,
                            )
                        prev_idle = idle_since

                    try:
                        daemon_state_file.write_text(_json.dumps({
                            "idle_since": idle_since,
                        }))
                    except Exception:
                        pass

                except Exception:
                    pass

                time.sleep(daemon_interval_s)
        finally:
            rtlog.log("daemon.exit", pid=my_pid, reason="terminated")
            try:
                daemon_pid_file.unlink(missing_ok=True)
            except OSError:
                pass
            try:
                daemon_state_file.unlink(missing_ok=True)
            except OSError:
                pass
            daemon_start_file = DAEMON_STATE_FILE.with_name("daemon.start")
            try:
                daemon_start_file.unlink(missing_ok=True)
            except OSError:
                pass


if __name__ == "__main__":
    main()
