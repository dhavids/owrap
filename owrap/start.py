import argparse
import secrets
import sys

from .base import BaseRunner
from .utils.paths import SESSION_DIR, TASKS_DIR, RUN_OUTPUT_DIR, EXEC_OUTPUT_DIR, READ_OUTPUT_DIR


class StartRunner(BaseRunner):
    def run(self, shell_pid=None, session_file=None):
        session_id = secrets.token_hex(3)
        url = self.manager.ensure_running()

        if session_file:
            session_path = type(session_file)(session_file) if not hasattr(session_file, "parent") else session_file
            session_path.parent.mkdir(parents=True, exist_ok=True)
            with open(session_path, "w") as f:
                f.write(f"session_id={session_id}\nserver_url={url}\n")

        TASKS_DIR.mkdir(parents=True, exist_ok=True)
        RUN_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        EXEC_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        READ_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        print(f"=== OWRAP SESSION STARTED ===")
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
    parser = argparse.ArgumentParser(description="Start an owrap session")
    parser.add_argument("--shell-pid", type=int, default=None, help="Shell PID")
    parser.add_argument("--session-file", type=str, default=None, help="Session file path")
    args = parser.parse_args()

    from .manager import Manager
    manager = Manager()
    StartRunner(manager).run(shell_pid=args.shell_pid, session_file=args.session_file)


if __name__ == "__main__":
    main()
