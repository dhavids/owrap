import sys
from pathlib import Path

from ..utils.paths import _read_config, DOCS_DIR, get_plan_path, session_input
from ..utils.session_resolver import resolve, remove_session, BY_CCSID_DIR, list_sessions, _parse
from ..manager import Manager


def _teardown_context(session_id: str):
    for suffix in (".md", ".lock"):
        p = DOCS_DIR / f"context_{session_id}{suffix}"
        p.unlink(missing_ok=True)


class StopRunner:
    def __init__(self, manager, logger=None, allow_all=False):
        self.manager = manager
        self.logger = logger
        self.allow_all = allow_all

    def run(self, session_file=None, no_exit=False, force=False, target=None):
        sessions_dir = Path.home() / ".owrap" / "sessions"
        global_session = Path.home() / ".owrap" / "session"
        config = _read_config()

        if force:
            Manager.stop_all(logger=self.logger)
            count = 0
            for s in list_sessions():
                sid = s["session_id"]
                remove_session(sid)
                _teardown_context(sid)
                pp = get_plan_path(sid)
                pp.unlink(missing_ok=True)
                ip = session_input(sid)
                ip.unlink(missing_ok=True)
                count += 1
            if global_session.exists():
                data = _parse(global_session)
                global_session.unlink(missing_ok=True)
                _teardown_context(data.get("session_id", ""))
                count += 1
            if BY_CCSID_DIR.exists():
                for ptr in BY_CCSID_DIR.iterdir():
                    if ptr.is_file():
                        ptr.unlink(missing_ok=True)
            if self.logger:
                self.logger.info("stop --force: all servers killed sessions cleared count=%d", count)
            print(f"OWRAP STOPPED  all servers killed  sessions cleared ({count} removed)")
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

        data = _parse(sf)
        server_url = data.get("server_url")

        # Find other sessions for server decision
        other_sessions = []
        for s in list_sessions():
            if s["session_id"] != sid:
                other_sessions.append({"session_id": s["session_id"], "url": s.get("server_url", "")})

        # Remove session file + by_ccsid pointer
        remove_session(sid)
        _teardown_context(sid)
        pp = get_plan_path(sid)
        pp.unlink(missing_ok=True)
        ip = session_input(sid)
        ip.unlink(missing_ok=True)

        use_multi = config.get("use_multiple_servers", False)
        if use_multi and server_url:
            same_server = [s for s in other_sessions if s["url"] == server_url]
            if not same_server:
                try:
                    port = int(server_url.rsplit(":", 1)[-1])
                    Manager(port=port).stop()
                    n = len(other_sessions)
                    if n:
                        print(f"OWRAP SESSION ENDED  server port {port} stopped  ({n} other session{'s' if n != 1 else ''} on other servers)")
                    else:
                        print(f"OWRAP STOPPED  server port {port} stopped  no other sessions")
                except (ValueError, Exception):
                    print("OWRAP SESSION ENDED  server stopped")
            else:
                n = len(other_sessions)
                print(f"OWRAP SESSION ENDED  server kept running ({n} other session{'s' if n != 1 else ''} active)")
        elif other_sessions:
            n = len(other_sessions)
            print(f"OWRAP SESSION ENDED  server kept running ({n} other session{'s' if n != 1 else ''} active)")
        else:
            self.manager.stop()
            print("OWRAP STOPPED  server killed  no other sessions")

        if not no_exit:
            sys.exit(0)
