import argparse
import shlex
import sys
from datetime import datetime
from pathlib import Path

from ..utils.terminal import Terminal
from ..manager import Manager
from ..base import BaseRunner
from ..utils.paths import TASKS_DIR


class ReadRunner(BaseRunner):
    TASKS_DIR = TASKS_DIR

    def _write_read_log(self, file_path: str):
        read_log = self.manager.read_log_path
        read_log.parent.mkdir(parents=True, exist_ok=True)
        entry = f"{datetime.now().strftime('%Y-%m-%d %H:%M')} — {file_path}\n"
        existing = ""
        if read_log.exists():
            try:
                existing = read_log.read_text()
            except Exception:
                pass
        read_log.write_text(entry + existing)

    def run(self, file_path, summarise=False, details=None, log_time=True):
        url = self.manager.ensure_running()

        prompt = f"Read the file at {file_path}"
        if summarise:
            prompt += ", summarise the content"
        if details:
            prompt += f", focusing on: {details}"
        prompt += ". Prioritise speed — no planning, no preamble, direct read and output."

        cmd = ["opencode", "run"]
        if self.allow_all:
            cmd.append("--dangerously-skip-permissions")
        if url:
            cmd.extend(["--attach", url])
            cmd.extend(["--", shlex.quote(prompt)])
        else:
            fallback_file = self.TASKS_DIR / "task0.md"
            fallback_file.write_text(f"## Do\n\n{prompt}\n")
            cmd = ["opencode", "run"]
            if self.allow_all:
                cmd.append("--dangerously-skip-permissions")
            cmd.extend(["--", "--task", shlex.quote(str(fallback_file))])

        self.manager.t_cmd_start()
        result = Terminal(verbose=False).run(" ".join(cmd), print_output=True, capture_output=True)
        self.manager.t_cmd_end()
        rc = result.get("returncode", 1)
        self._write_read_log(file_path)
        self.manager.log_time(log_time)
        sys.exit(rc)


def main():
    parser = argparse.ArgumentParser(description="Read a file via opencode")
    parser.add_argument("-f", "--file", required=True, help="File path to read")
    parser.add_argument("-s", "--summarise", action="store_true", help="Summarise content")
    parser.add_argument("-d", "--details", type=str, default=None, help="Focus details")
    parser.add_argument("--no-log-time", action="store_true", help="Suppress the timing block")
    args = parser.parse_args()
    manager = Manager()
    ReadRunner(manager).run(args.file, summarise=args.summarise, details=args.details,
                            log_time=not args.no_log_time)


if __name__ == "__main__":
    main()
