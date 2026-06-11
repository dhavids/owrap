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

        from ..utils.pool import get_pool, _active_load, _estimate_remaining
        pool = get_pool()

        running_tasks, done_tasks = self._load_tasks()
        all_srv_urls = {entry.get("url") for entry in pool}

        if pool:
            label = "server:" if len(pool) == 1 else "servers:"
            print(f"  {label}")
            for entry in pool:
                pid = entry.get("pid", "?")
                url = entry.get("url", "?")
                port = entry.get("port", "?")
                alive = "alive" if _is_alive(pid) else "dead"
                load = _active_load(url)
                remaining = _estimate_remaining(url)
                last_used = entry.get("last_used", 0)
                if load > 0:
                    lu_str = "in use"
                elif last_used:
                    lu_age = time.time() - last_used
                    if lu_age < 60:
                        lu_str = f"used {lu_age:.0f}s ago"
                    elif lu_age < 3600:
                        lu_str = f"used {lu_age/60:.0f}m ago"
                    else:
                        lu_str = f"used {lu_age/3600:.0f}h ago"
                else:
                    lu_str = "never used"
                print(f"    port {port}  {url}  [{alive}]  pid={pid}  load={load}  remaining={remaining:.0f}s  {lu_str}")
            print()
        else:
            print("  server: not started\n")

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
                        model = ks.get("model", "")
                        idle_since = ks.get("idle_since")
                        idle_exit_s = ks.get("idle_exit_s", 300)
                        model_str = f"  model={model}" if model else ""
                        if idle_since is not None:
                            remaining_idle = max(0, idle_exit_s - (time.time() - idle_since))
                            ka_extra = f"{model_str}  idle  dies in {remaining_idle:.0f}s"
                        else:
                            ka_extra = f"{model_str}  active"
                    except Exception:
                        pass
                print(f"  keepalive: pid={kpid} running{ka_extra}\n")
            except (ValueError, OSError):
                print("  keepalive: stopped\n")
        else:
            print("  keepalive: stopped\n")

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
        age = _age_str(t.get("started", time.time()))
        status = "running" if t.get("alive") else "stale/crashed"
        kind = t.get("kind", "task")
        tid = str(t.get("task_id", "?"))[:12]
        sess = f"  [{t.get('session_id','?')}/{t.get('research','?')}]" if show_session else ""
        health = t.get("health", "healthy") if status == "running" else None
        health_display = f"  {'STALLED' if health == 'stalled' else 'healthy'}" if health else ""
        print(f"{indent}{kind:<6}  {tid:<14}  {status:<14}  started {age} ago   pid={t.get('pid')}{sess}   \"{t.get('title','')[:55]}\"{health_display}")


def _print_done(tasks, show_session=True, indent="  "):
    for t in tasks:
        age = _age_str(t.get("finished", time.time()))
        rc = t.get("rc", "?")
        result = "ok" if rc == 0 else ("timeout" if t.get("timed_out") else ("crashed" if t.get("crashed") else f"rc={rc}"))
        kind = t.get("kind", "task")
        tid = str(t.get("task_id", "?"))[:12]
        sess = f"  [{t.get('session_id','?')}/{t.get('research','?')}]" if show_session else ""
        status = f"done({result})"
        started = t.get('started')
        finished = t.get('finished')
        dur_str = f'{finished - started:.1f}s' if started and finished else '?s'
        print(f"{indent}{kind:<6}  {tid:<14}  {status:<16}  {age} ago{sess}   {dur_str}   \"{t.get('title','')[:55]}\"")


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
