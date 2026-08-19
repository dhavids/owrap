import json
import os
import shlex
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

from ..utils.terminal import Terminal
from ..constants import ANTI_SUMMARY_SUFFIX, NO_OUTPUT_TASK_S
from ..utils.snippet import extract_snippet, divider
from ..utils.paths import (
    FALLBACK_EXEC_OUTPUT, FALLBACK_EXEC_LOG, FALLBACK_EXEC_STATUS,
    FALLBACK_TASK_OUTPUT, FALLBACK_TASK_LOG, FALLBACK_TASK_STATUS,
    _read_config, get_dispatch_model,
)


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description=(
            "Run a fallback --execf/--taskf opencode invocation directly "
            "(no server)"
        )
    )
    parser.add_argument(
        "path",
        help=(
            "Path to a plan or task .md file (mode inferred from filename: "
            "'task' in name -> --taskf, else --execf)"
        ),
    )
    args = parser.parse_args()
    FallbackRunner().run(args.path)


class FallbackRunner:
    """
    Execute opencode plans or tasks via a direct fallback invocation.
    """

    EXEC_OUTPUT = FALLBACK_EXEC_OUTPUT
    EXEC_LOG = FALLBACK_EXEC_LOG
    EXEC_STATUS = FALLBACK_EXEC_STATUS
    TASK_OUTPUT = FALLBACK_TASK_OUTPUT
    TASK_LOG = FALLBACK_TASK_LOG
    TASK_STATUS = FALLBACK_TASK_STATUS

    POLL_INTERVAL_S = 5
    STALL_THRESHOLD_S = 120
    STOP_MODES = {"tstop": "task", "estop": "exec"}

    def run(self, path):
        """
        Run a fallback opencode invocation or stop a running fallback.
        """
        if path in self.STOP_MODES:
            self.stop(self.STOP_MODES[path])
            return
        if not path:
            print("Error: a plan or task .md file path is required", file=sys.stderr)
            sys.exit(1)

        target = Path(path)
        if not target.exists():
            print(f"Error: {target} does not exist", file=sys.stderr)
            sys.exit(1)

        if "task" in target.name.lower():
            mode = "task"
            flag = "--taskf"
            output_log = self.TASK_OUTPUT
            run_log = self.TASK_LOG
            status_file = self.TASK_STATUS
        else:
            mode = "exec"
            flag = "--execf"
            output_log = self.EXEC_OUTPUT
            run_log = self.EXEC_LOG
            status_file = self.EXEC_STATUS

        cmd = ["opencode", "run", "--dangerously-skip-permissions"]
        fb_model = get_dispatch_model(_read_config(), default_to_fast=False)
        if fb_model:
            cmd.extend(["-m", fb_model])
        cmd.extend([
            "--",
            shlex.quote(f"--executor {flag} {target} {ANTI_SUMMARY_SUFFIX}"),
        ])

        output_log.parent.mkdir(parents=True, exist_ok=True)
        terminal = Terminal(verbose=False)
        result = terminal.run(" ".join(cmd), detached=True, print_output=True)
        runner_pid = result["pid"]

        status = {
            "target": str(target),
            "mode": mode,
            "started_at": datetime.now().isoformat(),
            "finished_at": None,
            "fallback_pid": os.getpid(),
            "runner_pid": runner_pid,
            "status": "running",
            "returncode": None,
        }
        self._write_status(status_file, status)

        last_growth = time.monotonic()
        poll_start = time.monotonic()
        first_output = False
        with open(output_log, "w") as log:
            log.write(
                f"[{datetime.now().isoformat()}] FALLBACK {mode.upper()} START "
                f"({target}, pid={runner_pid})\n"
            )
            log.flush()
            while terminal.is_running():
                time.sleep(self.POLL_INTERVAL_S)
                chunks_text = terminal.pop_clean_output()
                now = time.monotonic()
                if chunks_text:
                    log.write(chunks_text)
                    log.flush()
                    last_growth = now
                    first_output = True
                    if status["status"] == "stalled":
                        status["status"] = "running"
                        self._write_status(status_file, status)
                elif not first_output and now - poll_start >= NO_OUTPUT_TASK_S:
                    print(
                        f"[fallback] executor not responsive "
                        f"(no output in {NO_OUTPUT_TASK_S}s) "
                        f"— stop work immediately if you cannot edit files "
                        f"directly",
                        flush=True,
                    )
                    terminal.terminate_process()
                    status["status"] = "crashed"
                    self._write_status(status_file, status)
                    break
                elif (
                    now - last_growth > self.STALL_THRESHOLD_S
                    and status["status"] == "running"
                ):
                    status["status"] = "stalled"
                    self._write_status(status_file, status)

            chunks_text = terminal.pop_clean_output()
            if chunks_text:
                log.write(chunks_text)
                log.flush()

        rc = terminal._process.poll()
        if rc is None:
            rc = terminal._process.wait()

        status["finished_at"] = datetime.now().isoformat()
        status["returncode"] = rc
        status["status"] = "done" if rc == 0 else "crashed"
        if terminal.model:
            status["model"] = terminal.model
        self._write_status(status_file, status)

        self._write_log(run_log, target, rc)

        print(divider(f"[f:{mode}] completed"))
        print(f"status: {'SUCCESS' if rc == 0 else 'FAILED'}")
        print(f"exit: {rc}")
        print(f"output: {output_log}")
        print(f"status file: {status_file}")
        sys.exit(rc)

    def _write_status(self, status_file, status):
        import fcntl
        status_file.parent.mkdir(parents=True, exist_ok=True)
        status_file.touch(exist_ok=True)
        with open(status_file, "w") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            json.dump(status, f, indent=2)
            f.write("\n")

    def _write_log(self, run_log, target, rc):
        import fcntl
        run_log.parent.mkdir(parents=True, exist_ok=True)
        snippet = extract_snippet(target, default=target.name)
        entry = f"{datetime.now().strftime('%Y-%m-%d %H:%M')} — {snippet} (rc={rc})\n"
        run_log.touch(exist_ok=True)
        with open(run_log, "r+") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            existing = f.read()
            f.seek(0)
            f.write(entry + existing)
            f.truncate()

    def stop(self, mode):
        status_file = self.TASK_STATUS if mode == "task" else self.EXEC_STATUS
        run_log = self.TASK_LOG if mode == "task" else self.EXEC_LOG
        if not status_file.exists():
            print(
                f"No {mode} fallback status file found ({status_file})",
                file=sys.stderr,
            )
            sys.exit(1)
        status = json.loads(status_file.read_text())
        if status.get("status") not in ("running", "stalled"):
            print(f"{mode} fallback is not running (status={status.get('status')})")
            sys.exit(0)
        pid = status.get("runner_pid")
        if pid:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        status["status"] = "stopped"
        status["finished_at"] = datetime.now().isoformat()
        status["returncode"] = None
        self._write_status(status_file, status)
        target = Path(status.get("target", "?"))
        self._write_log(run_log, target, "stopped")
        print(f"Stopped {mode} fallback (pid={pid})")


if __name__ == "__main__":
    main()
