import json
import os
import sys
import time
from pathlib import Path

from ..base import BaseRunner
from ..utils.paths import STATE_FILE


class StatRunner(BaseRunner):
    def run(self, args):
        sessions_dir = Path.home() / ".owrap" / "sessions"
        global_session = Path.home() / ".owrap" / "session"
        current_id = os.environ.get("CLAUDE_CODE_SESSION_ID", "")

        state = self._read_state()

        print("=== OWRAP SESSIONS ===\n")

        if state:
            pid = state.get("pid")
            url = state.get("url", "?")
            tasks = state.get("tasks", {})
            active = sum(
                1 for t in tasks.values()
                if (t if isinstance(t, str) else t.get("status", "active")) == "active"
            )
            alive = False
            if pid:
                try:
                    os.kill(pid, 0)
                    alive = True
                except OSError:
                    pass
            status = "alive" if alive else "dead"
            log_file = state.get("log_file", "")
            log_info = ""
            if log_file:
                lp = Path(log_file)
                if lp.exists():
                    size = lp.stat().st_size
                    log_info = f"  log: {log_file} ({size} bytes)"
                else:
                    log_info = f"  log: {log_file} (missing)"
            print(f"  server: {url}  [{status}]  pid={pid}  tasks={active} active")
            if log_info:
                print(f" {log_info}")
            print()
        else:
            print("  server: not started\n")

        session_files = []
        if sessions_dir.exists():
            session_files = sorted(
                sessions_dir.glob("*.session"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )

        if session_files:
            print("sessions:")
            for sf in session_files:
                data = _parse_session(sf)
                claude_id = sf.stem
                marker = "  [current]" if claude_id == current_id else ""
                age = _age_str(sf.stat().st_mtime)
                print(f"  {claude_id}{marker}")
                print(f"    session:  {data.get('session_id', '?')}")
                research = data.get("research", "")
                if research:
                    print(f"    research: {research}")
                print(f"    age:      {age}")
                print()
        else:
            print("  (no scoped sessions found)\n")

        if global_session.exists():
            data = _parse_session(global_session)
            age = _age_str(global_session.stat().st_mtime)
            print("global (~/.owrap/session):")
            print(f"    session:  {data.get('session_id', '?')}")
            research = data.get("research", "")
            if research:
                print(f"    research: {research}")
            print(f"    age:      {age}")

        return 0

    def _read_state(self):
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return None


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


def _age_str(mtime: float) -> str:
    age = time.time() - mtime
    if age < 60:
        return f"{int(age)}s"
    if age < 3600:
        return f"{int(age / 60)}m"
    return f"{int(age / 3600)}h {int((age % 3600) / 60)}m"
