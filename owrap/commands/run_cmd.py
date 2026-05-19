import argparse
import json
import os
import re
import shlex
import sys
import time
from datetime import datetime
from pathlib import Path

from ..utils.terminal import Terminal
from ..manager import Manager
from ..base import BaseRunner
from ..utils.paths import TASKS_DIR, RUN_OUTPUT_DIR


class RunRunner(BaseRunner):
    TASKS_DIR = TASKS_DIR
    OUTPUT_DIR = RUN_OUTPUT_DIR

    def _get_task_title(self, task_file: Path) -> str:
        try:
            content = task_file.read_text()
            match = re.search(r'^## Do\s*\n+(.+)$', content, re.MULTILINE)
            if match:
                return match.group(1).strip()
        except Exception:
            pass
        return f"task{task_file.stem.replace('task', '')}"

    def _write_run_log(self, title: str, tag: str = ""):
        import fcntl
        run_log = self.manager.run_log_path
        run_log.parent.mkdir(parents=True, exist_ok=True)
        tag_str = f" {tag}" if tag else ""
        entry = f"{datetime.now().strftime('%Y-%m-%d %H:%M')}{tag_str} — {title}\n"
        run_log.touch(exist_ok=True)
        with open(run_log, "r+") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            existing = f.read()
            f.seek(0)
            f.write(entry + existing)
            f.truncate()

    def run(self, msg=None, msg_id=None, input_path=None, log_time=True, timeout=None):
        self._cleanup_recently_done()
        if self.logger:
            if msg is not None:
                self.logger.info("run msg=%.80r session=%s", msg, self.manager.session_id or "none")
            else:
                self.logger.info("run task session=%s", self.manager.session_id or "none")
        url = self.manager.ensure_running()

        if msg is not None:
            return self._run_msg(msg, url, log_time, msg_id=msg_id, timeout=timeout)
        return self._run_task(url, input_path, log_time)

    def _run_msg(self, msg, url, log_time, msg_id=None, timeout=None):
        self._install_sigterm_handler()
        if "\n" in msg:
            if self.logger:
                self.logger.error("run msg rejected: contains newlines session=%s", self.manager.session_id or "none")
            print("Error: --msg must be a single line (no newlines)", file=sys.stderr)
            sys.exit(1)
        if len(msg) > 1024:
            if self.logger:
                self.logger.error("run msg rejected: len=%d >1024 session=%s", len(msg), self.manager.session_id or "none")
            print("Error: --msg must be <= 1024 characters", file=sys.stderr)
            sys.exit(1)

        if msg_id:
            print(f"[m:{msg_id}]", flush=True)
        _msg_sentinel_id = msg_id or f"fg_{int(time.time())}"
        sentinel = self._write_sentinel(_msg_sentinel_id, msg[:60], kind="msg")
        cmd = ["opencode", "run"]
        if self.allow_all:
            cmd.append("--dangerously-skip-permissions")
        if url:
            cmd.extend(["--attach", url])
        cmd.extend(["--", "--task", "--do", shlex.quote(msg)])

        if not url:
            fallback_file = self.TASKS_DIR / "task0.md"
            fallback_file.write_text(f"## Do\n\n{msg}\n")
            cmd = ["opencode", "run"]
            if self.allow_all:
                cmd.append("--dangerously-skip-permissions")
            cmd.extend(["--", "--taskf", shlex.quote(str(fallback_file))])

        if self.logger:
            self.logger.debug("run msg cmd=%s", " ".join(cmd))
        MSG_TIMEOUT = timeout if timeout is not None else 180
        rc = 1
        timed_out = False
        try:
            self.manager.t_cmd_start()
            result = Terminal(verbose=False).run(" ".join(cmd), print_output=True, capture_output=True, timeout=MSG_TIMEOUT)
            self.manager.t_cmd_end()
            if result.get("timed_out"):
                timed_out = True
                partial = (result.get("stdout") or "").strip()
                chars = len(partial)
                print(flush=True)
                print(f"[orun --msg] timed out after {MSG_TIMEOUT}s ({chars} chars captured)", flush=True)
                print(f"  rerun with -t <seconds> to extend (default: 180s)", flush=True)
                rc = 2
            else:
                rc = result.get("returncode", 1)
        except Exception as exc:
            self.manager.t_cmd_end()
            if self.logger:
                self.logger.error("run msg error: %s", exc)
        finally:
            self._complete_sentinel(sentinel, rc, timed_out=timed_out)
            if self.logger:
                self.logger.info("run msg done rc=%d%s", rc, " (timeout)" if timed_out else "")
            self._write_run_log(msg[:80], tag=f"[m:{msg_id}]" if msg_id else "")
            self.manager.log_time(log_time)
        sys.exit(rc)

    def _run_task(self, url, input_path, log_time):
        if input_path is None:
            input_path = self.manager.input_path

        if not input_path.exists() or input_path.stat().st_size == 0:
            print("Error: input.md is empty or missing", file=sys.stderr)
            sys.exit(1)

        content = input_path.read_text()

        if url:
            task_id = self.manager.next_task_id()
            self.manager.register_task(task_id)
            task_file = self.TASKS_DIR / f"task{task_id}.md"
            task_file.write_text(content)
            input_path.write_text("")

            self.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            log_path = self.OUTPUT_DIR / f"task{task_id}.log"
            suffix = 1
            while log_path.exists():
                log_path = self.OUTPUT_DIR / f"task{task_id}_{suffix}.log"
                suffix += 1

            cmd = ["opencode", "run"]
            if self.allow_all:
                cmd.append("--dangerously-skip-permissions")
            cmd.extend(["--attach", url])
            cmd.extend(["--", "--task", shlex.quote(str(task_file))])

            title = self._get_task_title(task_file)
            sentinel = self._write_sentinel(task_id, title)
            self._install_sigterm_handler()
            if self.logger:
                self.logger.info("run task_id=%d title=%.60r session=%s", task_id, title, self.manager.session_id or "none")
                self.logger.debug("run task cmd=%s", " ".join(cmd))
            print(f"[t:{task_id}]", flush=True)

            rc = 1
            timed_out = False
            try:
                with open(log_path, "w") as log:
                    log.write(f"[{datetime.now().isoformat()}] TASK {task_id} START\n")
                    log.flush()
                    self.manager.t_cmd_start()
                    terminal = Terminal(verbose=False)
                    result = terminal.run(" ".join(cmd), capture_output=True, print_output=True, tee_file=log)
                    self.manager.t_cmd_end()
                    if result.get("timed_out"):
                        timed_out = True
                    rc = result.get("returncode", 1)
            except Exception as exc:
                self.manager.t_cmd_end()
                if self.logger:
                    self.logger.error("run task_id=%d error: %s", task_id, exc)
            finally:
                self._complete_sentinel(sentinel, rc, timed_out=timed_out)
                self.manager.complete_task(task_id)
                if self.logger:
                    self.logger.info("run task_id=%d done rc=%d log=%s%s", task_id, rc, log_path, " (timeout)" if timed_out else "")
                t = ""
                if self.manager._t_cmd_end is not None:
                    t = f"opencode={self.manager._t_cmd_end - self.manager._t_cmd_start:.1f}s  total={self.manager._t_cmd_end - self.manager._t_invocation:.1f}s"
                status = "SUCCESS" if rc == 0 else "FAILED"
                print(f"=== [task{task_id}] completed ===")
                print(f"status: {status}")
                print(f"exit: {rc}")
                print(f"log: {log_path}")
                if t:
                    print(f"timing: {t}")
                self.manager.log_time(log_time)
                self._write_run_log(title, tag=f"[t:{task_id}]")
        else:
            fallback_file = self.TASKS_DIR / "task0.md"
            fallback_file.write_text(content)
            input_path.write_text("")

            cmd = ["opencode", "run"]
            if self.allow_all:
                cmd.append("--dangerously-skip-permissions")
            cmd.extend(["--", "--taskf", shlex.quote(str(fallback_file))])

            title = self._get_task_title(fallback_file)
            self.manager.t_cmd_start()
            Terminal(verbose=False).run(" ".join(cmd), print_output=True)
            self.manager.t_cmd_end()
            rc = 0
            self.manager.log_time(log_time)
            self._write_run_log(title, tag=f"[t:0]")

        sys.exit(rc)


def main():
    parser = argparse.ArgumentParser(description="Run a task via opencode task")
    parser.add_argument("--msg", type=str, default=None, help="Single-line message for task mode")
    parser.add_argument("--id", "-i", type=str, default=None, help="Msg ID for parallel tracking")
    parser.add_argument("--input", type=str, default=None, help="Input file path (default: owrap/docs/run/input_<session_id>.md)")
    parser.add_argument("--no-log-time", action="store_true", help="Suppress the timing block")
    args = parser.parse_args()
    manager = Manager()
    RunRunner(manager).run(msg=args.msg, msg_id=args.id,
                           input_path=Path(args.input) if args.input else None,
                           log_time=not args.no_log_time)


if __name__ == "__main__":
    main()
