import sys
from pathlib import Path

from ..utils.paths import SESSION_DIR, _read_config
from ..manager import Manager


def _parse_session(path):
    data = {}
    try:
        for line in path.read_text().splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                data[k.strip()] = v.strip()
    except Exception:
        pass
    return data


class StopRunner:
    def __init__(self, manager, logger=None, allow_all=False):
        self.manager = manager
        self.logger = logger
        self.allow_all = allow_all

    def run(self, session_file=None, no_exit=False, force=False):
        sessions_dir = Path.home() / ".owrap" / "sessions"
        global_session = Path.home() / ".owrap" / "session"
        config = _read_config()
        use_multi = config.get("use_multiple_servers", False)

        if force:
            Manager.stop_all(logger=self.logger)
            count = 0
            if sessions_dir.exists():
                for sf in sessions_dir.glob("*.session"):
                    sf.unlink(missing_ok=True)
                    count += 1
            if global_session.exists():
                global_session.unlink(missing_ok=True)
                count += 1
            if self.logger:
                self.logger.info("stop --force: all servers killed sessions cleared count=%d", count)
            print(f"OWRAP STOPPED  all servers killed  sessions cleared ({count} removed)")
            if not no_exit:
                sys.exit(0)
            return

        # Non-force: determine current session's server
        current_name = Path(session_file).name if session_file else None
        current_server_url = None
        other_sessions = []

        if sessions_dir.exists():
            for sf in sessions_dir.glob("*.session"):
                data = _parse_session(sf)
                if sf.name == current_name:
                    current_server_url = data.get("server_url")
                else:
                    other_sessions.append({"file": sf, "url": data.get("server_url", "")})

        if session_file:
            Path(session_file).unlink(missing_ok=True)

        if use_multi and current_server_url:
            same_server = [s for s in other_sessions if s["url"] == current_server_url]
            if not same_server:
                try:
                    port = int(current_server_url.rsplit(":", 1)[-1])
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
