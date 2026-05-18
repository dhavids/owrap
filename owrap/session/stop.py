import sys
from pathlib import Path

from ..utils.paths import SESSION_DIR


class StopRunner:
    def __init__(self, manager):
        self.manager = manager

    def run(self, session_file=None):
        sessions_dir = Path.home() / ".owrap" / "sessions"
        global_session = Path.home() / ".owrap" / "session"

        self.manager.stop()

        count = 0
        if sessions_dir.exists():
            for sf in sessions_dir.glob("*.session"):
                sf.unlink(missing_ok=True)
                count += 1
        if global_session.exists():
            global_session.unlink(missing_ok=True)
            count += 1

        print(f"OWRAP STOPPED  server killed  sessions cleared ({count} removed)")
        sys.exit(0)
