import sys
from pathlib import Path

from ..utils.paths import _read_config
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


class EndRunner:
    def __init__(self, manager, logger=None, allow_all=False):
        self.manager = manager
        self.logger = logger
        self.allow_all = allow_all

    def run(self, session_file=None):
        sessions_dir = Path.home() / ".owrap" / "sessions"
        config = _read_config()
        use_multi = config.get("use_multiple_servers", False)

        session_id = ""
        current_server_url = None

        if session_file:
            sp = Path(session_file)
            if sp.exists():
                data = _parse_session(sp)
                session_id = data.get("session_id", "")
                current_server_url = data.get("server_url")
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

        if self.logger:
            self.logger.info("end session=%s", session_id)
        print(f"OWRAP SESSION ENDED  session: {session_id}")
        sys.exit(0)
