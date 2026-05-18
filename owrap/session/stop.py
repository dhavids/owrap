import sys
from pathlib import Path

from ..utils.paths import SESSION_DIR


class StopRunner:
    def __init__(self, manager, logger=None, allow_all=False):
        self.manager = manager
        self.logger = logger
        self.allow_all = allow_all

    def run(self, session_file=None, no_exit=False):
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

        if self.logger:
            self.logger.info("stop: sessions cleared count=%d", count)
        print(f"OWRAP STOPPED  server killed  sessions cleared ({count} removed)")
        if not no_exit:
            sys.exit(0)
