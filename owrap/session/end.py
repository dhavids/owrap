import sys
from pathlib import Path

from ..utils.paths import _read_config, DOCS_DIR, context_path, context_lock_path
from ..utils.session_resolver import list_sessions, _parse as _parse_sf


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

    def run(self, session_file=None, target=None):
        sessions_dir = Path.home() / ".owrap" / "sessions"

        session_id = ""

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
                context_path(session_id).unlink(missing_ok=True)
                context_lock_path(session_id).unlink(missing_ok=True)
                sp.unlink(missing_ok=True)

        if self.logger:
            self.logger.info("end session=%s", session_id)
        print(f"OWRAP SESSION ENDED  session: {session_id}")
        sys.exit(0)
