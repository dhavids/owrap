import argparse
import re
import shlex
import sys
from datetime import datetime
from pathlib import Path

from ..utils.terminal import Terminal
from ..manager import Manager
from ..base import BaseRunner
from ..utils.paths import EXEC_OUTPUT_DIR, get_plan_path, context_path, _read_config, get_agents_md_path, get_workspace_path


class ExecRunner(BaseRunner):
    LOG_DIR = EXEC_OUTPUT_DIR

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
        sid = self.manager.session_id or "exec"
        self.LOG_FILE = EXEC_OUTPUT_DIR / f"exec_output_{sid}.log"
        self._cleanup_recently_done()
        session_id = self.manager.session_id
        plan_path = get_plan_path(session_id) if session_id else None

        if self.logger:
            self.logger.info("exec session=%s plan=%s", session_id or "none", plan_path or "none")
        url = self.manager.ensure_running()

        cmd = ["opencode", "run"]
        if self.allow_all:
            cmd.append("--dangerously-skip-permissions")
        _ctx_cfg = _read_config()
        cp = context_path(session_id) if session_id else None
        ctx_instr = None
        executor_md = get_agents_md_path()
        if _ctx_cfg.get("context_enabled", True) and cp and cp.exists() and cp.stat().st_size > 0:
            if executor_md and executor_md.exists():
                ctx_instr = f"First read {executor_md}, then read {cp}, then: "
            else:
                ctx_instr = f"First read {cp}, then: "
        plan_str = str(plan_path) if plan_path else ""
        exec_msg = f"--exec {plan_str}".strip()
        if url:
            cmd.extend(["--attach", url])
            prompt = f"{ctx_instr}{exec_msg}" if ctx_instr else exec_msg
            cmd.extend(["--", shlex.quote(prompt)])
        else:
            execf_msg = f"--execf {plan_str}".strip()
            fb_prompt = f"{ctx_instr}{execf_msg}" if ctx_instr else execf_msg
            cmd.extend(["--", shlex.quote(fb_prompt)])

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

        sentinel = self._write_sentinel(session_id or "exec", plan_name[:60], kind="exec")
        self._install_sigterm_handler()
        rc = 1
        try:
            with open(self.LOG_FILE, "w") as log:
                log.write(f"[{datetime.now().isoformat()}] EXEC SESSION START\n")
                log.flush()
                self.manager.t_cmd_start()
                terminal = Terminal(verbose=False)
                result = terminal.run(" ".join(cmd), capture_output=True, print_output=True, tee_file=log, cwd=str(get_workspace_path()))
                self.manager.t_cmd_end()
                rc = result.get("returncode", 1)
        finally:
            self._complete_sentinel(sentinel, rc)

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
        _ctx_remind = context_path(session_id)
        if _ctx_remind and _ctx_remind.exists():
            print(f"\n→ Planner: update {_ctx_remind} — Focus (what changed), Key Locations (new paths), Decisions (architectural choices).")
        self.manager.log_time(log_time)
        self._write_exec_log(plan_name)
        try:
            self.manager.append_context_recent(plan_name, rc, ctx=ctx_instr is not None, kind="exec")
            self.manager.refresh_context_plan(plan_path)
            self.manager.update_frequent_files()
        except Exception:
            pass

        sys.exit(rc)


def main():
    parser = argparse.ArgumentParser(description="Execute the active plan via opencode")
    parser.add_argument("--no-log-time", action="store_true", help="Suppress the timing block")
    args = parser.parse_args()
    manager = Manager()
    ExecRunner(manager).run(log_time=not args.no_log_time)


if __name__ == "__main__":
    main()
