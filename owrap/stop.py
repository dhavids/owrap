import argparse
import sys
from pathlib import Path


class StopRunner:
    def __init__(self, manager):
        self.manager = manager

    def run(self, session_file=None):
        session_id = self.manager.session_id
        if session_file:
            sp = Path(session_file)
            if sp.exists():
                content = sp.read_text()
                for line in content.splitlines():
                    if line.startswith("session_id="):
                        session_id = line.split("=", 1)[1]
                sp.unlink()

        print(f"OWRAP SESSION STOPPED  session: {session_id}")
        sys.exit(0)


def main():
    parser = argparse.ArgumentParser(description="Stop an owrap session")
    parser.add_argument("--session-file", type=str, default=None, help="Session file path")
    args = parser.parse_args()

    from .manager import Manager
    manager = Manager()
    StopRunner(manager).run(session_file=args.session_file)


if __name__ == "__main__":
    main()
