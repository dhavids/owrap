import os
import sys
import time
from pathlib import Path

from ..base import BaseRunner


TWO_HOURS = 2 * 3600


class CleanupRunner(BaseRunner):
    def run(self, args):
        partial = getattr(args, "session_id", None)
        sessions_dir = Path.home() / ".owrap" / "sessions"
        global_session = Path.home() / ".owrap" / "session"

        state = self.manager._read_state()
        server_alive = False
        server_url = None
        if state:
            pid = state.get("pid")
            server_url = state.get("url")
            if pid:
                try:
                    os.kill(pid, 0)
                    server_alive = True
                except OSError:
                    pass

        removed = []
        now = time.time()

        if partial:
            if sessions_dir.exists():
                for sf in sessions_dir.glob("*.session"):
                    data = _parse_session(sf)
                    if data.get("session_id", "").startswith(partial) or sf.stem.startswith(partial):
                        sf.unlink(missing_ok=True)
                        removed.append(sf.name)
            if global_session.exists():
                data = _parse_session(global_session)
                if data.get("session_id", "").startswith(partial):
                    global_session.unlink(missing_ok=True)
                    removed.append("session (global)")
        else:
            if sessions_dir.exists():
                for sf in sessions_dir.glob("*.session"):
                    age = now - sf.stat().st_mtime
                    is_ppid = sf.stem.isdigit()
                    if age > TWO_HOURS or is_ppid:
                        sf.unlink(missing_ok=True)
                        removed.append(sf.name)
            if global_session.exists():
                age = now - global_session.stat().st_mtime
                if age > TWO_HOURS:
                    global_session.unlink(missing_ok=True)
                    removed.append("session (global)")
            if not server_alive and state is not None:
                self.manager.stop()
                removed.append("manager.json (dead server state)")

        if removed:
            print(f"Cleaned up {len(removed)} item(s):")
            for name in removed:
                print(f"  {name}")
        else:
            status = "server alive" if server_alive else "server dead, nothing to remove"
            print(f"Nothing to clean up. ({status})")

        return 0


def _parse_session(path: Path) -> dict:
    data = {}
    try:
        for line in path.read_text().splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                data[k.strip()] = v.strip()
    except Exception:
        pass
    return data
