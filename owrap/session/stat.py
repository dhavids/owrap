import json
import os
import sys
import time
from pathlib import Path

from ..base import BaseRunner
from ..utils.paths import RUNNING_DIR, RECENTLY_DONE_DIR, session_input


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

        print("=== OWRAP SESSIONS ===\n")

        from ..manager import Manager as _Manager
        servers = _Manager.list_servers()
        sess_counts = _Manager.sessions_per_server()

        running_tasks, done_tasks = self._load_tasks()
        all_srv_urls = {srv.get("url") for srv in servers}

        if servers:
            label = "server:" if len(servers) == 1 else "servers:"
            print(f"  {label}")
            _active_by_url = {}
            _last_task_time = {}
            for _t in running_tasks:
                _u = _t.get("server_url", "")
                if _t.get("alive"):
                    _active_by_url[_u] = _active_by_url.get(_u, 0) + 1
                _ts = _t.get("started", 0)
                if _ts > _last_task_time.get(_u, 0):
                    _last_task_time[_u] = _ts
            for _t in done_tasks:
                _u = _t.get("server_url", "")
                _ts = _t.get("finished", 0)
                if _ts > _last_task_time.get(_u, 0):
                    _last_task_time[_u] = _ts
            servers = sorted(
                servers,
                key=lambda s: (
                    _active_by_url.get(s.get("url", ""), 0),
                    _last_task_time.get(s.get("url", ""), 0),
                ),
                reverse=True,
            )
            for srv in servers:
                pid = srv.get("pid", "?")
                url = srv.get("url", "?")
                port = srv.get("port", "?")
                session_count = sess_counts.get(url, 0)

                srv_running = [t for t in running_tasks if t.get("server_url") == url]
                srv_done = [t for t in done_tasks if t.get("server_url") == url]
                active_count = sum(1 for t in srv_running if t.get("alive"))

                log_file = srv.get("log_file", "")
                log_info = ""
                if log_file:
                    lp = Path(log_file)
                    if lp.exists():
                        log_info = f"log: {lp.name} ({lp.stat().st_size} bytes)"
                print(f"    port {port}  {url}  [alive]  pid={pid}  tasks={active_count} active  sessions={session_count}")
                if log_info:
                    print(f"    {log_info}")
                if srv_running or srv_done:
                    print("    tasks:")
                    _print_running(srv_running, show_session=True, indent="      ")
                    _print_done(srv_done, show_session=True, indent="      ")
                print()
        else:
            print("  server: not started\n")

        orphan_running = [t for t in running_tasks if t.get("server_url", "") not in all_srv_urls]
        orphan_done = [t for t in done_tasks if t.get("server_url", "") not in all_srv_urls]
        if orphan_running or orphan_done:
            print("tasks:")
            _print_running(orphan_running, show_session=True)
            _print_done(orphan_done, show_session=True)
            print()

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
                server_url = data.get("server_url", "")
                if server_url:
                    print(f"    server:   {server_url}")
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

    def _load_tasks(self):
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
                    running.append(data)
                except Exception:
                    pass
        done = []
        if RECENTLY_DONE_DIR.exists():
            for f in sorted(RECENTLY_DONE_DIR.iterdir()):
                try:
                    data = json.loads(f.read_text())
                    done.append(data)
                except Exception:
                    pass
        return running, done

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


def _print_running(tasks, show_session=True, indent="  "):
    for t in tasks:
        age = _age_str(t.get("started", time.time()))
        status = "running" if t.get("alive") else "stale/crashed"
        kind = t.get("kind", "task")
        tid = str(t.get("task_id", "?"))[:12]
        sess = f"  [{t.get('session_id','?')}/{t.get('research','?')}]" if show_session else ""
        print(f"{indent}{kind:<6}  {tid:<14}  {status:<14}  started {age} ago   pid={t.get('pid')}{sess}   \"{t.get('title','')[:55]}\"")


def _print_done(tasks, show_session=True, indent="  "):
    for t in tasks:
        age = _age_str(t.get("finished", time.time()))
        rc = t.get("rc", "?")
        result = "ok" if rc == 0 else ("timeout" if t.get("timed_out") else ("crashed" if t.get("crashed") else f"rc={rc}"))
        kind = t.get("kind", "task")
        tid = str(t.get("task_id", "?"))[:12]
        sess = f"  [{t.get('session_id','?')}/{t.get('research','?')}]" if show_session else ""
        status = f"done({result})"
        print(f"{indent}{kind:<6}  {tid:<14}  {status:<16}  {age} ago{sess}   \"{t.get('title','')[:55]}\"")


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
