import json
import os
import shutil
import sys
import time
from pathlib import Path

from ..base import BaseRunner
from ..utils.paths import _read_config, DOCS_DIR, RUNTIME_DIR, get_plan_path, session_input, context_path, context_lock_path, SERVER_LOGS_DIR, SERVERS_DIR, RUNNING_DIR, RECENTLY_DONE_DIR, SESSION_DIR, session_dir
from ..utils.session_resolver import resolve, remove_session, BY_CCSID_DIR, list_sessions, _parse
from ..utils.trash import move_to_trash, restore_from_trash


class StopRunner:
    def __init__(self, manager, logger=None, allow_all=False):
        self.manager = manager
        self.logger = logger
        self.allow_all = allow_all

    def run(self, session_file=None, no_exit=False, force=False, target=None):
        sessions_dir = SESSION_DIR / "sessions"
        global_session = SESSION_DIR / "session"
        config = _read_config()

        if force:
            KillServersRunner().run()
            count = 0
            for s in list_sessions():
                sid = s["session_id"]
                move_to_trash(sid)
                remove_session(sid)
                count += 1
            if global_session.exists():
                data = _parse(global_session)
                gsid = data.get("session_id", "")
                global_session.unlink(missing_ok=True)
                if gsid:
                    move_to_trash(gsid)
                count += 1
            if BY_CCSID_DIR.exists():
                for ptr in BY_CCSID_DIR.iterdir():
                    if ptr.is_file():
                        ptr.unlink(missing_ok=True)
            if self.logger:
                self.logger.info("stop --force: all servers killed sessions moved to trash count=%d", count)
            print(f"OWRAP STOPPED  all servers killed  {count} session(s) moved to .trash (restore any with `owrap restore trash [session_id]`)")
            if not no_exit:
                sys.exit(0)
            return

        # Non-force: determine current session via resolver
        sid = None
        sf = None

        if target:
            for s in list_sessions():
                if s["session_id"].startswith(target) or s.get("research", "") == target:
                    sid = s["session_id"]
                    sf = sessions_dir / f"{sid}.session"
                    break
            if sid is None:
                print(f"OWRAP STOP: no session matching '{target}'. Use `owrap stop --force` to clear everything.")
                sys.exit(0)
        else:
            sid, sf, _ = resolve(mode="refresh")

        if sid is None:
            print("OWRAP STOP: no current session to stop. Use `owrap stop --force` to clear everything.")
            sys.exit(0)

        # Move session file + docs/runtime/context to .trash; clear by_ccsid pointer
        move_to_trash(sid)
        remove_session(sid)

        # Find other sessions
        other_sessions = []
        for s in list_sessions():
            if s["session_id"] != sid:
                other_sessions.append(s["session_id"])

        n = len(other_sessions)
        if n:
            print(f"OWRAP SESSION ENDED  ({n} other session{'s' if n != 1 else ''} active)")
        else:
            print("OWRAP STOPPED  no other sessions")

        if not no_exit:
            sys.exit(0)


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


def _kill_pid(pid: int, signum: int = 15) -> bool:
    try:
        os.kill(pid, signum)
        return True
    except OSError:
        return False


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _wait_dead(pids: list[int], timeout: float = 3.0):
    deadline = time.time() + timeout
    remaining = list(pids)
    while remaining and time.time() < deadline:
        time.sleep(0.2)
        remaining = [p for p in remaining if _pid_alive(p)]
    for p in remaining:
        _kill_pid(p, 9)


def _cleanup_context(session_id: str, removed: list):
    for suffix in (".md", ".lock"):
        p = DOCS_DIR / f"context_{session_id}{suffix}"
        if p.exists():
            p.unlink(missing_ok=True)
            removed.append(f"context_{session_id}{suffix}")


class EndRunner:
    def __init__(self, manager, logger=None, allow_all=False):
        self.manager = manager
        self.logger = logger
        self.allow_all = allow_all

    def run(self, session_file=None, target=None):
        sessions_dir = SESSION_DIR / "sessions"

        session_id = ""
        matched_sid = ""

        if target:
            for s in list_sessions():
                if s["session_id"].startswith(target) or s.get("research", "") == target:
                    matched_sid = s["session_id"]
                    session_file = str(sessions_dir / f"{matched_sid}.session")
                    break
            else:
                print(f"OWRAP END: no session matching '{target}'.")
                sys.exit(0)

        if session_file is None and self.manager.session_id:
            if target:
                print(f"OWRAP END: no session matching '{target}'.")
                sys.exit(0)
            candidate = SESSION_DIR / 'sessions' / f'{self.manager.session_id}.session'
            if candidate.exists():
                session_file = str(candidate)

        if session_file:
            sp = Path(session_file)
            if sp.exists():
                data = _parse_session(sp)
                session_id = data.get("session_id", "") or matched_sid
                if not session_id:
                    print(f"OWRAP END: could not determine session_id from '{session_file}' — aborting.")
                    sys.exit(1)
                if target and not session_id.startswith(target) and target not in (session_id, data.get("research", "")):
                    print(f"OWRAP END: resolved session '{session_id}' does not match target '{target}' — aborting.")
                    sys.exit(1)

        if session_id:
            move_to_trash(session_id)
            remove_session(session_id)

        if self.logger:
            self.logger.info("end session=%s", session_id)
        if session_id:
            print(f"OWRAP SESSION ENDED  session: {session_id}  (moved to .trash — restore with `owrap restore trash {session_id}`)")
        else:
            print("OWRAP SESSION ENDED  session: (none resolved)")
        sys.exit(0)


class RestoreRunner(BaseRunner):
    def run(self, args):
        session_id = args.session_id
        try:
            restore_from_trash(session_id)
        except FileNotFoundError as e:
            print(f"Error: {e}")
            return 1
        print(f"OWRAP RESTORED  session: {session_id}  (run `owrap attach {session_id}` to bind this window to it)")
        return 0


class KillServersRunner:
    def __init__(self, manager=None, logger=None, allow_all=False):
        pass

    def run(self, session_id: str | None = None):
        from ..utils.pool import POOL_FILE, _read_pool

        killed_tasks = 0
        killed_servers = 0
        task_pids = []

        if RUNNING_DIR.exists():
            for sentinel in RUNNING_DIR.glob("*.json"):
                try:
                    data = json.loads(sentinel.read_text())
                    if session_id and data.get("session_id") != session_id:
                        continue
                    pid = data.get("pid")
                    if pid and _pid_alive(pid):
                        _kill_pid(pid)
                        task_pids.append(pid)
                        killed_tasks += 1
                    data["rc"] = -9
                    data["killed"] = True
                    data["ended"] = time.time()
                    RECENTLY_DONE_DIR.mkdir(parents=True, exist_ok=True)
                    (RECENTLY_DONE_DIR / sentinel.name).write_text(json.dumps(data))
                    sentinel.unlink(missing_ok=True)
                except Exception:
                    try:
                        sentinel.unlink(missing_ok=True)
                    except Exception:
                        pass

        if task_pids:
            _wait_dead(task_pids)

        pool = _read_pool()
        server_pids = []
        for entry in pool:
            pid = entry.get("pid")
            if pid and _pid_alive(pid):
                _kill_pid(pid)
                server_pids.append(pid)
                killed_servers += 1

        if server_pids:
            _wait_dead(server_pids)

        try:
            POOL_FILE.unlink(missing_ok=True)
        except Exception:
            pass

        if SERVERS_DIR.exists():
            for f in SERVERS_DIR.glob("*.json"):
                try:
                    f.unlink()
                except Exception:
                    pass

        parts = []
        if killed_tasks:
            parts.append(f"{killed_tasks} task{'s' if killed_tasks != 1 else ''}")
        if killed_servers:
            parts.append(f"{killed_servers} server{'s' if killed_servers != 1 else ''}")
        if parts:
            print(f"killed {' and '.join(parts)}")
        else:
            print("nothing running")


class CleanupRunner(BaseRunner):
    TWO_HOURS = 2 * 3600

    def run(self, args):
        partial = getattr(args, "session_id", None)
        sessions_dir = SESSION_DIR / "sessions"
        global_session = SESSION_DIR / "session"

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
                        _cleanup_context(data.get("session_id", sf.stem), removed)
            if global_session.exists():
                data = _parse_session(global_session)
                if data.get("session_id", "").startswith(partial):
                    global_session.unlink(missing_ok=True)
                    removed.append("session (global)")
                    _cleanup_context(data.get("session_id", ""), removed)
        else:
            if sessions_dir.exists():
                for sf in sessions_dir.glob("*.session"):
                    age = now - sf.stat().st_mtime
                    is_ppid = sf.stem.isdigit()
                    if age > self.TWO_HOURS or is_ppid:
                        sf.unlink(missing_ok=True)
                        data = _parse_session(sf)
                        removed.append(sf.name)
                        _cleanup_context(data.get("session_id", sf.stem), removed)
            if global_session.exists():
                age = now - global_session.stat().st_mtime
                if age > self.TWO_HOURS:
                    global_session.unlink(missing_ok=True)
                    data = _parse_session(global_session)
                    removed.append("session (global)")
                    _cleanup_context(data.get("session_id", ""), removed)
            if not server_alive and state is not None:
                self.manager.stop()
                removed.append("manager.json (dead server state)")

        active_sids = set()
        if sessions_dir.exists():
            for sf in sessions_dir.glob("*.session"):
                data = _parse_session(sf)
                sid = data.get("session_id", "").strip()
                if sid:
                    active_sids.add(sid)
        if DOCS_DIR.exists():
            for suffix in (".md", ".lock"):
                for f in DOCS_DIR.glob(f"context_*{suffix}"):
                    sid = f.stem.replace("context_", "")
                    if sid not in active_sids:
                        f.unlink(missing_ok=True)
                        removed.append(f.name)

        for f in SERVER_LOGS_DIR.glob("owrap_start_*.log"):
            f.unlink(missing_ok=True)
            removed.append(f.name)

        for f in SERVER_LOGS_DIR.glob("owrap_*.log"):
            if f.name.startswith("owrap_start_"):
                continue
            try:
                pid = int(f.stem.replace("owrap_", ""))
                os.kill(pid, 0)
            except (ValueError, OSError):
                f.unlink(missing_ok=True)
                removed.append(f.name)

        if SERVERS_DIR.exists():
            for f in SERVERS_DIR.glob("*.json"):
                try:
                    data = json.loads(f.read_text())
                    pid = data.get("pid")
                    if pid:
                        os.kill(pid, 0)
                except OSError:
                    f.unlink(missing_ok=True)
                    removed.append(f"servers/{f.name}")
                except Exception:
                    pass

        if removed:
            print(f"Cleaned up {len(removed)} item(s):")
            for name in removed:
                print(f"  {name}")
        else:
            status = "server alive" if server_alive else "server dead, nothing to remove"
            print(f"Nothing to clean up. ({status})")

        return 0
