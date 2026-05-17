import argparse
import sys
from pathlib import Path

from ..base import BaseRunner
from .start import StartRunner
from ..utils.paths import SESSION_DIR, get_plan_path, get_self_path, get_todo_path, session_input
from .orientation import print_orientation


class RefreshRunner(BaseRunner):
    def run(self, shell_pid=None, session_file=None, research=None):
        if session_file is None:
            session_file = SESSION_DIR / "session"
        if not Path(session_file).exists():
            StartRunner(self.manager).run(shell_pid=shell_pid, session_file=session_file, research=research)
            return

        url = self.manager.get_url()
        if url is None:
            StartRunner(self.manager).run(shell_pid=shell_pid, session_file=session_file, research=research)
            return

        session_id = self.manager.session_id
        sp = Path(session_file)
        for line in sp.read_text().splitlines():
            if line.startswith("session_id="):
                session_id = line.split("=", 1)[1]
                break

        plan_path = get_plan_path(session_id)
        todo_path = get_todo_path()
        self_path = get_self_path()
        input_path = session_input(session_id)

        print_orientation(session_id, research, url, plan_path, todo_path, self_path, input_path)
        sys.exit(0)


def main():
    parser = argparse.ArgumentParser(description="Refresh an owrap session")
    parser.add_argument("research", nargs="?", default=None, help="Research project name")
    parser.add_argument("--shell-pid", type=int, default=None, help="Shell PID")
    parser.add_argument("--session-file", type=str, default=None, help="Session file path")
    args = parser.parse_args()

    from ..manager import Manager
    manager = Manager()
    RefreshRunner(manager).run(shell_pid=args.shell_pid, session_file=args.session_file, research=args.research)


if __name__ == "__main__":
    main()
