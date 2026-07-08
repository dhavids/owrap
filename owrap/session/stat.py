import json
import os
import sys
import time
from pathlib import Path

from ..base import BaseRunner
from ..utils.paths import RUNNING_DIR, RECENTLY_DONE_DIR, session_input, _read_config, SERVER_LOGS_DIR, SESSION_DIR


class StatRunner(BaseRunner):
    def run(self, args):
        filter_arg = getattr(args, 'filter', None)

        self._cleanup_recently_done()

        if filter_arg is not None:
            self._show_tasks(filter_arg)
            return 0

        sessions_dir = SESSION_DIR / "sessions"
        global_session = SESSION_DIR / "session"
        current_id = os.environ.get("CLAUDE_CODE_SESSION_ID", "")

        print("=== OWRAP SESSIONS ===\n")

        # keepalive status
        from ..utils.paths import KEEPALIVE_PID_FILE, KEEPALIVE_STATE_FILE
        keepalive_pid_file = KEEPALIVE_PID_FILE
        keepalive_state_file = KEEPALIVE_STATE_FILE
        if keepalive_pid_file.exists():
            try:
                kpid = int(keepalive_pid_file.read_text().strip())
                os.kill(kpid, 0)
                ka_extra = ""
                if keepalive_state_file.exists():
                    try:
                        import json as _json
                        ks = _json.loads(keepalive_state_file.read_text())
                        idle_since = ks.get("idle_since")
                        idle_exit_s = ks.get("idle_exit_s", 300)
                        if idle_since is not None:
                            remaining_idle = max(0, idle_exit_s - (time.time() - idle_since))
                            ka_extra = f"  idle  dies in {remaining_idle:.0f}s"
                        else:
                            ka_extra = "  active"
                    except Exception:
                        pass
                print(f"  keepalive: pid={kpid} running{ka_extra}\n")
            except (ValueError, OSError):
                print("  keepalive: stopped\n")
        else:
            print("  keepalive: stopped\n")

        from ..utils.pool import get_pool, _active_load, _estimate_remaining
        pool = get_pool()

        running_tasks, done_tasks = self._load_tasks()
        all_srv_urls = {entry.get("url") for entry in pool}

        if pool:
            label = "server:" if len(pool) == 1 else f"servers ({len(pool)}):"
            print(f"  {label}")
            cfg = _read_config()
            idle_shutdown_s = float(cfg.get("idle_shutdown_s", 600))
            now = time.time()
            for i, entry in enumerate(pool):
                if i > 0:
                    print()
                pid = entry.get("pid", "?")
                url = entry.get("url", "?")
                alive = "alive" if _is_alive(pid) else "dead"
                load = _active_load(url)
                last_used = entry.get("last_used", 0)
                if last_used:
                    dies_in = max(0, idle_shutdown_s - (now - last_used))
                    if load > 0:
                        dies_str = ""
                    elif dies_in > 0:
                        dies_str = f"  dies in {dies_in:.0f}s"
                    else:
                        dies_str = "  idle (kept alive)"
                else:
                    dies_str = ""
                log_file = SERVER_LOGS_DIR / f"owrap_{pid}.log"
                log_str = f"  {log_file}" if log_file.exists() else ""
                print(f"    {url}  load={load}{dies_str}{log_str}")
                srv_running = [t for t in running_tasks if t.get("server_url") == url]
                srv_done = [t for t in done_tasks if t.get("server_url") == url]
                if srv_running or srv_done:
                    print(f"      tasks:")
                    _print_running(srv_running, show_session=True, indent="        ")
                    _print_done(srv_done, show_session=True, indent="        ")
            print()
        else:
            print("  server: not started\n")

        dead_urls = {}
        for t in running_tasks + done_tasks:
            url = t.get("server_url", "")
            if url and url not in all_srv_urls:
                dead_urls.setdefault(url, [])
        dead_urls_sorted = sorted(dead_urls.keys())

        if dead_urls_sorted:
            if not pool:
                print(f"  servers ({len(dead_urls_sorted)}):")
            for url in dead_urls_sorted:
                ghost_running = [t for t in running_tasks if t.get("server_url") == url]
                ghost_done = [t for t in done_tasks if t.get("server_url") == url]
                print(f"    {url}  [dead]")
                if ghost_running or ghost_done:
                    print(f"      tasks:")
                    _print_running(ghost_running, show_session=True, indent="        ")
                    _print_done(ghost_done, show_session=True, indent="        ")
            print()

        orphan_running = [t for t in running_tasks if not t.get("server_url")]
        orphan_done = [t for t in done_tasks if not t.get("server_url")]
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
                area = data.get("area", "")
                if area:
                    print(f"    area:     {area}")
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
            area = data.get("area", "")
            if area:
                print(f"    area:     {area}")
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


def _is_alive(pid) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _print_running(tasks, show_session=True, indent="  "):
    for t in tasks:
        alive = t.get("alive", False)
        health = t.get("health", "healthy") if alive else None
        if not alive:
            status = "stale/crashed"
        elif health == "stalled":
            status = "STALLED"
        else:
            status = "running"
        elapsed = time.time() - t.get("started", time.time())
        dur_str = f"{elapsed:.0f}s"
        kind = t.get("kind", "task")
        sess = f"  [{t.get('session_id','?')}]" if show_session else ""
        out = t.get("output_path", "")
        out_str = f"  {out}" if out else ""
        print(f"{indent}{kind}  {sess}  {status}  {dur_str}{out_str}")


def _print_done(tasks, show_session=True, indent="  "):
    for t in tasks:
        finished_age = _age_str(t.get("finished", time.time()))
        rc = t.get("rc", "?")
        result = "ok" if rc == 0 else ("timeout" if t.get("timed_out") else ("crashed" if t.get("crashed") else f"rc={rc}"))
        kind = t.get("kind", "task")
        sess = f"  [{t.get('session_id','?')}]" if show_session else ""
        status = f"done({result})"
        started = t.get("started")
        finished = t.get("finished")
        dur_str = f"{finished - started:.1f}s" if started and finished else "?s"
        out = t.get("output_path", "")
        out_str = f"  {out}" if out else ""
        print(f"{indent}{kind}  {sess}  {status}  {finished_age} ago  {dur_str}{out_str}")


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
