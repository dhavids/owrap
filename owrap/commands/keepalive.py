import os
import sys
import time
from pathlib import Path

from ..base import BaseRunner
from ..utils.pool import get_pool, _active_load, shutdown_idle, ensure_min_servers
from ..utils.paths import _read_config


def main():
    """Entry point for the keepalive daemon process."""
    from ..manager import Manager
    manager = Manager()
    KeepaliveRunner(manager).run()


class KeepaliveRunner(BaseRunner):
    """Background daemon that manages pool lifecycle: shuts down idle
    servers and maintains minimum server count."""
    def run(self):
        """Run the keepalive daemon loop: manage pool lifecycle and idle shutdown."""
        from ..utils.paths import KEEPALIVE_PID_FILE, KEEPALIVE_STATE_FILE
        keepalive_pid_file = KEEPALIVE_PID_FILE
        my_pid = os.getpid()
        try:
            import subprocess as _sp
            result = _sp.run(
                ["pgrep", "-f", "owrap.runner keepalive"],
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
        keepalive_pid_file.write_text(str(my_pid))

        keepalive_start_file = KEEPALIVE_STATE_FILE.with_name("keepalive.start")
        try:
            if not keepalive_start_file.exists():
                keepalive_start_file.write_text(str(time.time()))
        except Exception:
            pass

        config = _read_config()
        idle_shutdown_s = float(config.get("idle_shutdown_s", 240))
        keepalive_interval_s = float(config.get("keepalive_interval_s", 10))
        keepalive_idle_exit_s = float(config.get("keepalive_idle_exit_s", 300))
        keepalive_state_file = KEEPALIVE_STATE_FILE
        idle_since = None
        import json as _json
        try:
            while True:
                try:
                    pool = get_pool()
                    total_load = sum(_active_load(e["url"]) for e in pool)
                    if total_load == 0:
                        if idle_since is None:
                            idle_since = time.time()
                        elif time.time() - idle_since >= keepalive_idle_exit_s:
                            break
                        shutdown_idle(idle_s=idle_shutdown_s)
                    else:
                        idle_since = None
                        shutdown_idle(idle_s=idle_shutdown_s)
                    ensure_min_servers()

                    try:
                        keepalive_state_file.write_text(_json.dumps({
                            "idle_since": idle_since,
                            "idle_exit_s": keepalive_idle_exit_s,
                        }))
                    except Exception:
                        pass

                except Exception:
                    pass

                time.sleep(keepalive_interval_s)
        finally:
            try:
                keepalive_pid_file.unlink(missing_ok=True)
            except OSError:
                pass
            try:
                keepalive_state_file.unlink(missing_ok=True)
            except OSError:
                pass
            keepalive_start_file = KEEPALIVE_STATE_FILE.with_name("keepalive.start")
            try:
                keepalive_start_file.unlink(missing_ok=True)
            except OSError:
                pass


if __name__ == "__main__":
    main()
