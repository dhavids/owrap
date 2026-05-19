import json
import os
import sys
import time
from pathlib import Path

from ..base import BaseRunner
from ..utils.paths import STATE_FILE, RUNNING_DIR, RECENTLY_DONE_DIR, session_input


class StatRunner(BaseRunner):
    def run(self, args):
        filter_arg = getattr(args, 'filter', None)

        self._cleanup_recently_done()

        if filter_arg is not None:
            self._show_tasks(filter_arg)
            return 0

        sessions_dir = Path.home() / ".owrap" / "sessions"
        global_session = Path.home() / ".owrap" / "session"
        current_id = os.environ.get("CLAUDE_CODE_SESSION_ID", "")

        state = self._read_state()

        print("=== OWRAP SESSIONS ===\n")

        if state:
            pid = state.get("pid")
            url = state.get("url", "?")
            active = 0
            if RUNNING_DIR.exists():
                for _sf in RUNNING_DIR.iterdir():
                    try:
                        _d = json.loads(_sf.read_text())
                        _pid = _d.get("pid")
                        if _pid:
                            try:
                                os.kill(_pid, 0)
                                active += 1
                            except OSError:
                                pass
                    except Exception:
                        pass
            alive = False
            responsive = False
            if pid:
                try:
                    os.kill(pid, 0)
                    alive = True
                except OSError:
                    pass
            if alive:
                url_to_check = state.get("url", "")
                if url_to_check:
                    import socket
                    try:
                        addr = url_to_check.replace("http://", "").replace("https://", "")
                        parts = addr.rsplit(":", 1)
                        host = parts[0]
                        port = int(parts[1]) if len(parts) > 1 else 4096
                        with socket.create_connection((host, port), timeout=3):
                            responsive = True
                    except (OSError, ValueError):
                        pass
            status = "alive" if responsive else ("unresponsive" if alive else "dead")
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

        self._show_tasks(None)

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

    def _show_tasks(self, filter_arg=None):
        def _matches(t):
            if filter_arg is None:
                return True
            return t.get("session_id") == filter_arg

        running = []
        if RUNNING_DIR.exists():
            for f in sorted(RUNNING_DIR.iterdir()):
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
                    data["alive"] = alive
                    if _matches(data):
                        running.append(data)
                except Exception:
                    pass

        done = []
        if RECENTLY_DONE_DIR.exists():
            for f in sorted(RECENTLY_DONE_DIR.iterdir()):
                try:
                    data = json.loads(f.read_text())
                    if _matches(data):
                        done.append(data)
                except Exception:
                    pass

        if filter_arg is not None:
            all_sids = {t.get("session_id") for t in running + done if t.get("session_id")}
            if filter_arg not in all_sids:
                all_sids.add(filter_arg)

            print(f"tasks [{filter_arg}]:")

            if not running and not done:
                print("  (no running or recently-done tasks)")
            else:
                _print_running(running, show_session=False)
                _print_done(done, show_session=False)

            queued = []
            for sid in sorted(all_sids):
                try:
                    qpath = session_input(sid)
                    if qpath.exists() and qpath.read_text().strip():
                        queued.append(str(qpath))
                except Exception:
                    pass
            if queued:
                print(f"  queue: {len(queued)} staged — {', '.join(queued)}")
            else:
                print("  queue: empty")
            print()
        else:
            if not running and not done:
                return
            print("tasks:")
            _print_running(running, show_session=True)
            _print_done(done, show_session=True)
            print()


def _print_running(tasks, show_session=True):
    for t in tasks:
        age = _age_str(t.get("started", time.time()))
        status = "running" if t.get("alive") else "stale/crashed"
        kind = t.get("kind", "task")
        tid = str(t.get("task_id", "?"))[:12]
        sess = f"  [{t.get('session_id','?')}/{t.get('research','?')}]" if show_session else ""
        print(f"  {kind:<6}  {tid:<14}  {status:<14}  started {age} ago   pid={t.get('pid')}{sess}   \"{t.get('title','')[:55]}\"")


def _print_done(tasks, show_session=True):
    for t in tasks:
        age = _age_str(t.get("finished", time.time()))
        rc = t.get("rc", "?")
        result = "ok" if rc == 0 else ("timeout" if t.get("timed_out") else ("crashed" if t.get("crashed") else f"rc={rc}"))
        kind = t.get("kind", "task")
        tid = str(t.get("task_id", "?"))[:12]
        sess = f"  [{t.get('session_id','?')}/{t.get('research','?')}]" if show_session else ""
        status = f"done({result})"
        print(f"  {kind:<6}  {tid:<14}  {status:<16}  {age} ago{sess}   \"{t.get('title','')[:55]}\"")


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
