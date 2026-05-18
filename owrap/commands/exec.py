import argparse
import re
import shlex
import sys
from datetime import datetime
from pathlib import Path

from ..utils.terminal import Terminal
from ..manager import Manager
from ..base import BaseRunner
from ..utils.paths import EXEC_OUTPUT_DIR, get_plan_path


class ExecRunner(BaseRunner):
    LOG_DIR = EXEC_OUTPUT_DIR
    LOG_FILE = EXEC_OUTPUT_DIR / "exec_output.log"

    def _get_active_plan_name(self, plan_path: Path | None = None) -> str:
        if plan_path is None:
            plan_path = get_plan_path(self.manager.session_id) if self.manager.session_id else None
        if plan_path is None:
            return "exec"
        try:
            content = plan_path.read_text()
            match = re.search(r'^## \[ACTIVE\]\s+(.+)$', content, re.MULTILINE)
            if match:
                return match.group(1).split(' — ')[0].strip()
        except Exception:
            pass
        return "exec"

    def _write_exec_log(self, plan_name: str):
        exec_log = self.manager.exec_log_path
        exec_log.parent.mkdir(parents=True, exist_ok=True)
        entry = f"{datetime.now().strftime('%Y-%m-%d %H:%M')} — {plan_name}\n"
        existing = ""
        if exec_log.exists():
            try:
                existing = exec_log.read_text()
            except Exception:
                pass
        exec_log.write_text(entry + existing)

    def run(self, log_time=True):
        session_id = self.manager.session_id
        plan_path = get_plan_path(session_id) if session_id else None

        if self.logger:
            self.logger.info("exec session=%s plan=%s", session_id or "none", plan_path or "none")
        url = self.manager.ensure_running()

        cmd = ["opencode", "run"]
        if self.allow_all:
            cmd.append("--dangerously-skip-permissions")
        if url:
            cmd.extend(["--attach", url])
            if plan_path:
                cmd.extend(["--", "--exec", shlex.quote(str(plan_path))])
            else:
                cmd.extend(["--", "--exec"])
        else:
            cmd.extend(["--", "--execf"])

        plan_name = self._get_active_plan_name(plan_path)

        if self.logger:
            self.logger.debug("exec cmd=%s", " ".join(cmd))
        self.LOG_DIR.mkdir(parents=True, exist_ok=True)
        if self.LOG_FILE.exists():
            try:
                self.LOG_FILE.unlink()
            except OSError:
                ts = datetime.now().strftime("%H%M%S")
                self.LOG_FILE = self.LOG_FILE.parent / f"{self.LOG_FILE.stem}_{ts}{self.LOG_FILE.suffix}"
        with open(self.LOG_FILE, "w") as log:
            log.write(f"[{datetime.now().isoformat()}] EXEC SESSION START\n")
            log.flush()
            self.manager.t_cmd_start()
            terminal = Terminal(verbose=False)
            result = terminal.run(" ".join(cmd), capture_output=True, print_output=True, tee_file=log)
            self.manager.t_cmd_end()
            rc = result.get("returncode", 1)

        t = ""
        if self.manager._t_cmd_end is not None:
            t = f"opencode={self.manager._t_cmd_end - self.manager._t_cmd_start:.1f}s  total={self.manager._t_cmd_end - self.manager._t_invocation:.1f}s"
        status = "SUCCESS" if rc == 0 else "FAILED"
        if self.logger:
            self.logger.info("exec done rc=%d status=%s log=%s", rc, status, self.LOG_FILE)
        print(f"=== [exec] completed ===")
        print(f"status: {status}")
        print(f"exit: {rc}")
        print(f"log: {self.LOG_FILE}")
        if t:
            print(f"timing: {t}")
        self.manager.log_time(log_time)
        self._write_exec_log(plan_name)

        sys.exit(rc)


def main():
    parser = argparse.ArgumentParser(description="Execute the active plan via opencode")
    parser.add_argument("--no-log-time", action="store_true", help="Suppress the timing block")
    args = parser.parse_args()
    manager = Manager()
    ExecRunner(manager).run(log_time=not args.no_log_time)


if __name__ == "__main__":
    main()
