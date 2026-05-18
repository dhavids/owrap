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

    def _run_grep(self, pattern: str, file_path=None):
        import subprocess
        target = Path(file_path) if file_path else Path.cwd()
        if self.logger:
            self.logger.info("grep pattern=%r target=%s session=%s", pattern, target, self.manager.session_id or "none")
        if target.is_file():
            cmd = ["grep", "-n", pattern, str(target)]
        else:
            cmd = ["grep", "-rn", pattern, str(target)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.stdout:
            print(result.stdout, end="")
        if result.returncode == 1:
            print(f"(no matches for {pattern!r} in {target})")
        elif result.returncode not in (0, 1):
            print(result.stderr, end="", file=sys.stderr)
        sys.exit(0)

    def _write_read_log(self, file_path: str, tag: str = ""):
        import fcntl
        read_log = self.manager.read_log_path
        read_log.parent.mkdir(parents=True, exist_ok=True)
        tag_str = f" {tag}" if tag else ""
        entry = f"{datetime.now().strftime('%Y-%m-%d %H:%M')}{tag_str} — {file_path}\n"
        read_log.touch(exist_ok=True)
        with open(read_log, "r+") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            existing = f.read()
            f.seek(0)
            f.write(entry + existing)
            f.truncate()

    LARGE_FILE_LINES = 500

    def run(self, file_path, summarise=False, details=None, log_time=True, grep=None, read_id=None):
        if grep is not None:
            self._run_grep(grep, file_path)
            return
        if read_id:
            print(f"[r:{read_id}]", flush=True)
        if self.logger:
            self.logger.info("read file=%s session=%s", file_path, self.manager.session_id or "none")
            if details:
                self.logger.debug("read details=%r", details)
        if not summarise and details is None:
            import subprocess
            p = Path(file_path)
            if not p.exists():
                print(f"{file_path}: does not exist")
                sys.exit(1)
            elif p.is_dir():
                result = subprocess.run(["ls", str(p)])
                sys.exit(result.returncode)
            else:
                text = p.read_text()
                line_count = text.count("\n") + (1 if text and not text.endswith("\n") else 0)
                if line_count <= self.LARGE_FILE_LINES:
                    print(text, end="")
                    self._write_read_log(file_path, tag=f"[r:{read_id}]" if read_id else "")
                    sys.exit(0)
                print(f"[oread] {line_count} lines (>{self.LARGE_FILE_LINES}) — forwarding to opencode for summary", flush=True)
                summarise = True

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

        TIMEOUT = 55
        if self.logger:
            self.logger.debug("read cmd=%s", " ".join(cmd))
        self.manager.t_cmd_start()
        result = Terminal(verbose=False).run(" ".join(cmd), print_output=True, capture_output=True, timeout=TIMEOUT)
        self.manager.t_cmd_end()

        if result.get("timed_out"):
            partial = (result.get("stdout") or "").strip()
            chars = len(partial)
            print(flush=True)
            print(f"[oread] timed out after {TIMEOUT}s", flush=True)
            print(f"  partial output printed above ({chars} chars captured)", flush=True)
            print(f"  the file or query is too large for -d — try -s (summarise) instead", flush=True)
            self._write_read_log(file_path, tag=f"[r:{read_id}]" if read_id else "")
            self.manager.log_time(log_time)
            sys.exit(2)

        rc = result.get("returncode", 1)
        self._write_read_log(file_path, tag=f"[r:{read_id}]" if read_id else "")
        self.manager.log_time(log_time)
        sys.exit(rc)


def main():
    parser = argparse.ArgumentParser(description="Read a file via opencode")
    parser.add_argument("-f", "--file", required=True, help="File path to read")
    parser.add_argument("-s", "--summarise", action="store_true", help="Summarise content")
    parser.add_argument("-d", "--details", type=str, default=None, help="Focus details")
    parser.add_argument("--id", "-i", type=str, default=None, help="Read ID for parallel tracking")
    parser.add_argument("--no-log-time", action="store_true", help="Suppress the timing block")
    args = parser.parse_args()
    manager = Manager()
    ReadRunner(manager).run(args.file, summarise=args.summarise, details=args.details,
                            log_time=not args.no_log_time, read_id=args.id)


if __name__ == "__main__":
    main()
