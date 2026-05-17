import argparse
import sys
from pathlib import Path

from .base import BaseRunner
from .start import StartRunner


class RefreshRunner(BaseRunner):
    def run(self, shell_pid=None, session_file=None):
        if session_file is None or not Path(session_file).exists():
            StartRunner(self.manager).run(shell_pid=shell_pid, session_file=session_file)
            return

        url = self.manager.get_url()
        if url is None:
            StartRunner(self.manager).run(shell_pid=shell_pid, session_file=session_file)
            return

        session_id = self.manager.session_id
        sp = Path(session_file)
        for line in sp.read_text().splitlines():
            if line.startswith("session_id="):
                session_id = line.split("=", 1)[1]
                break

        print(f"=== OWRAP SESSION REFRESHED ===")
        print(f"  session:  {session_id}")
        print(f"  server:   {url}")
        print(f"  commands: oread -f <file> [-s] [-d ...]")
        print(f"            orun --msg \"...\"   |   orun  (file task)")
        print(f"            oexec")
        print(f"  parallel: write input_{session_id}.md → orun → wait for clear → repeat")
        print(f"  stop:     owrap stop")
        print(f"  refresh:  owrap refresh")
        sys.exit(0)


def main():
    parser = argparse.ArgumentParser(description="Refresh an owrap session")
    parser.add_argument("--shell-pid", type=int, default=None, help="Shell PID")
    parser.add_argument("--session-file", type=str, default=None, help="Session file path")
    args = parser.parse_args()

    from .manager import Manager
    manager = Manager()
    RefreshRunner(manager).run(shell_pid=args.shell_pid, session_file=args.session_file)


if __name__ == "__main__":
    main()
