import sys
from pathlib import Path


class EndRunner:
    def __init__(self, manager, logger=None, allow_all=False):
        self.manager = manager
        self.logger = logger
        self.allow_all = allow_all

    def run(self, session_file=None):
        session_id = ""
        if session_file:
            sp = Path(session_file)
            if sp.exists():
                for line in sp.read_text().splitlines():
                    if line.startswith("session_id="):
                        session_id = line.split("=", 1)[1].strip()
                sp.unlink(missing_ok=True)
        if self.logger:
            self.logger.info("end session=%s", session_id)
        print(f"OWRAP SESSION ENDED  session: {session_id}")
        sys.exit(0)
