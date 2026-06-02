import sys
from pathlib import Path

from ..utils.paths import _read_config, DOCS_DIR
from ..utils.session_resolver import list_sessions, _parse as _parse_sf
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


def _teardown_context(session_id: str):
    for suffix in (".md", ".lock"):
        p = DOCS_DIR / f"context_{session_id}{suffix}"
        p.unlink(missing_ok=True)


class EndRunner:
    def __init__(self, manager, logger=None, allow_all=False):
        self.manager = manager
        self.logger = logger
        self.allow_all = allow_all

    def run(self, session_file=None, target=None):
        sessions_dir = Path.home() / ".owrap" / "sessions"
        config = _read_config()
        use_multi = config.get("use_multiple_servers", False)

        session_id = ""
        current_server_url = None

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
            candidate = Path.home() / '.owrap' / 'sessions' / f'{self.manager.session_id}.session'
            if candidate.exists():
                session_file = str(candidate)

        if session_file:
            sp = Path(session_file)
            if sp.exists():
                data = _parse_session(sp)
                session_id = data.get("session_id", "")
                current_server_url = data.get("server_url")
                _teardown_context(session_id)
                sp.unlink(missing_ok=True)

        if use_multi and current_server_url:
            # Check if any remaining sessions use the same server
            same_server = []
            if sessions_dir.exists():
                for sf in sessions_dir.glob("*.session"):
                    d = _parse_session(sf)
                    if d.get("server_url") == current_server_url:
                        same_server.append(sf)
            if not same_server:
                try:
                    port = int(current_server_url.rsplit(":", 1)[-1])
                    Manager(port=port).stop()
                    if self.logger:
                        self.logger.info("end: stopped server port=%d session=%s", port, session_id)
                    print(f"OWRAP SESSION ENDED  session: {session_id}  server port {port} stopped")
                    sys.exit(0)
                except (ValueError, Exception):
                    pass
        elif current_server_url:
            same_server = []
            if sessions_dir.exists():
                for sf in sessions_dir.glob("*.session"):
                    d = _parse_session(sf)
                    if d.get("server_url") == current_server_url:
                        same_server.append(sf)
            if not same_server:
                try:
                    port = int(current_server_url.rsplit(":", 1)[-1])
                    Manager(port=port).stop()
                    if self.logger:
                        self.logger.info("end: stopped server port=%d session=%s (single-server mode)", port, session_id)
                    print(f"OWRAP SESSION ENDED  session: {session_id}  server port {port} stopped")
                    sys.exit(0)
                except (ValueError, Exception):
                    pass

        if self.logger:
            self.logger.info("end session=%s", session_id)
        print(f"OWRAP SESSION ENDED  session: {session_id}")
        sys.exit(0)
