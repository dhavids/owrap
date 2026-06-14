import os
import sys
import time
from pathlib import Path

from ..base import BaseRunner
from ..utils.pool import get_pool, _active_load, shutdown_idle
from ..utils.paths import _read_config
from ..utils.terminal import Terminal


class KeepaliveRunner(BaseRunner):
    """Background daemon that pings pool servers to prevent cold-start and shuts down idle ones."""
    def run(self):
        from ..utils.paths import KEEPALIVE_PID_FILE, KEEPALIVE_STATE_FILE
        keepalive_pid_file = KEEPALIVE_PID_FILE
        keepalive_pid_file.write_text(str(os.getpid()))

        config = _read_config()
        idle_shutdown_s = float(config.get("idle_shutdown_s", 240))
        keepalive_interval_s = float(config.get("keepalive_interval_s", 10))
        keepalive_idle_exit_s = float(config.get("keepalive_idle_exit_s", 300))
        keepalive_ping_model = config.get("keepalive_ping_model", "opencode/deepseek-v4-flash-free")
        keepalive_state_file = KEEPALIVE_STATE_FILE
        idle_since = None
        try:
            while True:
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

                import json as _json
                try:
                    keepalive_state_file.write_text(_json.dumps({
                        "model": keepalive_ping_model,
                        "idle_since": idle_since,
                        "idle_exit_s": keepalive_idle_exit_s,
                    }))
                except Exception:
                    pass

                pool = get_pool()
                for entry in pool:
                    elapsed = time.time() - entry.get("last_used", 0)
                    # Only ping servers that haven't been used in the last 20s
                    # (servers used recently are already warm)
                    if elapsed > 20:
                        url = entry.get("url")
                        if url:
                            try:
                                msg = "What is 2+2? Just the number. STOP immediately when done. DO NOT summarize, list, or explain your work."
                                # ping: cheap request to keep the opencode server session warm and prevent cold-start penalty
                                # Use server's default model (do not override with -m)
                                cmd = f"opencode run --pure --attach {url} -m {keepalive_ping_model} -- {msg!r}"
                                Terminal(verbose=False).run(cmd, capture_output=True, print_output=False, timeout=15)
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


def main():
    """Entry point for the keepalive daemon process."""
    from ..manager import Manager
    manager = Manager()
    KeepaliveRunner(manager).run()


if __name__ == "__main__":
    main()
