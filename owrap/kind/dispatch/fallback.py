import fcntl
import json
import os
import shlex
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

from . import Dispatch
from ...dispatch import work
from ...utils.constants import ANTI_SUMMARY_SUFFIX, NO_OUTPUT_TASK_S
from ...utils.dispatch.terminal import Terminal
from ...utils.parser.snippet import divider, extract_snippet
from ...utils.paths import (
    FALLBACK_EXEC_LOG, FALLBACK_EXEC_OUTPUT, FALLBACK_EXEC_STATUS,
    FALLBACK_TASK_LOG, FALLBACK_TASK_OUTPUT, FALLBACK_TASK_STATUS,
    _read_config, get_dispatch_model,
)

POLL_INTERVAL_S = 5
STALL_THRESHOLD_S = 120
_MODE_FILES = {
    "task": (FALLBACK_TASK_OUTPUT, FALLBACK_TASK_LOG, FALLBACK_TASK_STATUS),
    "exec": (FALLBACK_EXEC_OUTPUT, FALLBACK_EXEC_LOG, FALLBACK_EXEC_STATUS),
}


class Fallback(Dispatch):
    """
    Runs an opencode `--execf`/`--taskf` invocation directly, with no
    server attached -- the `owrap f` command, used when the normal
    pool-backed dispatch path is down. Deliberately independent of
    the sentinel/pool machinery every other `Dispatch` kind shares
    (that's the point of being the fallback: it must still work when
    that machinery is what's broken) -- its own status-file state
    machine, addressed by a `task`/`exec` mode singleton slot rather
    than a task id, so it doesn't fit `Dispatch.get`'s sentinel
    lookup either. Overrides `get` directly for that reason.
    """

    kind = "fallback"

    usage = {
        "start": {
            "usage": "<path>",
            "args": [("path", "a plan or task .md file ('task' in the "
                              "name -> --taskf, else --execf)")],
            "examples": ["plan.md", "task_1.md"],
            "purpose": "Run a direct fallback task or plan",
            "group": "dispatch",
        },
        "done": {
            "usage": "<task|exec>",
            "args": [("mode", "which fallback slot to stop")],
            "examples": ["task", "exec"],
        },
        "get": {
            "usage": "<task|exec>",
            "args": [("mode", "which fallback slot to report")],
            "examples": ["task", "exec"],
        },
    }


    # Public Methods

    def start(self, path: str) -> None:
        """
        Run `path` through a direct, serverless opencode invocation,
        polling its output for growth/stall until it exits.
        """
        if not path:
            self._fail("a plan or task .md file path is required")
        target = Path(path)
        if not target.exists():
            self._fail(f"{target} does not exist")

        mode = "task" if "task" in target.name.lower() else "exec"
        flag = "--taskf" if mode == "task" else "--execf"
        output_log, run_log, status_file = _MODE_FILES[mode]

        cmd = ["opencode", "run", "--dangerously-skip-permissions"]
        fb_model = get_dispatch_model(_read_config(), default_to_fast=False)
        if fb_model:
            cmd.extend(["-m", fb_model])
        cmd.extend([
            "--", shlex.quote(f"--executor {flag} {target} {ANTI_SUMMARY_SUFFIX}"),
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

        rc = self._poll_until_done(terminal, output_log, status_file, status, mode)

        status["finished_at"] = datetime.now().isoformat()
        status["returncode"] = rc
        status["status"] = "done" if rc == 0 else "crashed"
        if terminal.model:
            status["model"] = terminal.model
        self._write_status(status_file, status)
        work.prepend_log_entry(
            run_log, f"{extract_snippet(target, default=target.name)} (rc={rc})",
        )

        print(divider(f"[f:{mode}] completed"))
        print(f"status: {'SUCCESS' if rc == 0 else 'FAILED'}")
        print(f"exit: {rc}")
        print(f"output: {output_log}")
        print(f"status file: {status_file}")
        sys.exit(rc)

    def done(self, mode: str = None) -> None:
        """
        SIGTERM the still-running fallback invocation in `mode`'s
        slot (`task` or `exec`) and mark its status file `stopped`.
        """
        if mode not in _MODE_FILES:
            self._usage("done")
        _, run_log, status_file = _MODE_FILES[mode]
        if not status_file.exists():
            self._fail(f"no {mode} fallback status file found ({status_file})")
        status = json.loads(status_file.read_text())
        if status.get("status") not in ("running", "stalled"):
            print(f"{mode} fallback is not running (status={status.get('status')})")
            return
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
        work.prepend_log_entry(
            run_log, f"{extract_snippet(target, default=target.name)} (rc=stopped)",
        )
        print(f"Stopped {mode} fallback (pid={pid})")

    def get(self, mode: str = None) -> None:
        """
        Report `mode`'s (`task`/`exec`) fallback status file --
        overrides `Dispatch.get` directly since this kind has no
        sentinel for `work.find_task` to look up.
        """
        if mode not in _MODE_FILES:
            self._usage("get")
        _, _, status_file = _MODE_FILES[mode]
        if not status_file.exists():
            self._fail(f"no {mode} fallback status file found ({status_file})")
        print(json.dumps(json.loads(status_file.read_text()), indent=2))


    # Private Methods

    def _poll_until_done(self, terminal, output_log, status_file, status, mode) -> int:
        last_growth = time.monotonic()
        poll_start = time.monotonic()
        first_output = False
        with open(output_log, "w") as log:
            log.write(
                f"[{datetime.now().isoformat()}] FALLBACK {mode.upper()} START "
                f"({status['target']}, pid={status['runner_pid']})\n"
            )
            log.flush()
            while terminal.is_running():
                time.sleep(POLL_INTERVAL_S)
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
                    now - last_growth > STALL_THRESHOLD_S
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
        return rc

    def _write_status(self, status_file, status) -> None:
        status_file.parent.mkdir(parents=True, exist_ok=True)
        status_file.touch(exist_ok=True)
        with open(status_file, "w") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            json.dump(status, f, indent=2)
            f.write("\n")
