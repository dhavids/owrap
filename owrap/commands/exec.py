import argparse
import os
import shlex
import sys
from datetime import datetime
from pathlib import Path

from ..utils.terminal import Terminal
from ..manager import Manager
from ..base import BaseRunner
from ..constants import ANTI_SUMMARY_SUFFIX, EXEC_KILL_S, NO_OUTPUT_EXEC_S
from ..utils.pool import _pool_active, pick_server, update_last_used
from ..utils.paths import session_exec_output_path, get_plan_path, context_path, _read_config, get_agents_md_path, get_workspace_path, format_failure_pointer
from ..utils.snippet import extract_snippet, divider


class ExecRunner(BaseRunner):

    def _get_active_plan_name(self, plan_path: Path | None = None) -> str:
        if plan_path is None:
            plan_path = get_plan_path(self.manager.session_id) if self.manager.session_id else None
        if plan_path is None:
            return "exec"
        return extract_snippet(plan_path, default="exec")

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

    def run(self, log_time=False):
        sid = self.manager.session_id or "exec"
        self.LOG_FILE = session_exec_output_path(sid)
        print(f"log: {self.LOG_FILE}", flush=True)
        self._cleanup_recently_done()
        session_id = self.manager.session_id
        plan_path = get_plan_path(session_id) if session_id else None

        if self.logger:
            self.logger.info("exec session=%s plan=%s", session_id or "none", plan_path or "none")

        if _pool_active():
            try:
                url = pick_server("exec")
            except Exception:
                print(format_failure_pointer("NO_SERVER", session_id))
                sys.exit(1)
        else:
            url = self.manager.ensure_running()

        cmd = ["opencode", "run", "--thinking"]
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
        exec_msg += " " + ANTI_SUMMARY_SUFFIX
        if url:
            cmd.extend(["--attach", url])
            prompt = f"{ctx_instr}{exec_msg}" if ctx_instr else exec_msg
            cmd.extend(["--", shlex.quote(prompt)])
        else:
            execf_msg = f"--execf {plan_str}".strip()
            fb_prompt = f"{ctx_instr}{execf_msg}" if ctx_instr else execf_msg
            fb_prompt += " " + ANTI_SUMMARY_SUFFIX
            cmd.extend(["--", shlex.quote(fb_prompt)])

        plan_name = self._get_active_plan_name(plan_path)

        if self.logger:
            self.logger.debug("exec cmd=%s", " ".join(cmd))
        self.LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        if self.LOG_FILE.exists():
            try:
                self.LOG_FILE.unlink()
            except OSError:
                ts = datetime.now().strftime("%H%M%S")
                self.LOG_FILE = self.LOG_FILE.parent / f"{self.LOG_FILE.stem}_{ts}{self.LOG_FILE.suffix}"

        task_id = session_id or "exec"
        self.manager.register_task(task_id, "exec")
        sentinel = self._write_sentinel(task_id, plan_name[:60], kind="exec", call_type="exec", url=url, output_path=self.LOG_FILE)
        self._install_sigterm_handler()
        rc = 1
        watchdog = None
        try:
            with open(self.LOG_FILE, "w") as log:
                log.write(f"[{datetime.now().isoformat()}] EXEC SESSION START\n\n")
                log.write(f"{divider('INPUT')}\n\nPlan file: {plan_str}\n\n")
                log.flush()
                log.write(f"{divider('EXECUTOR OUTPUT')}\n")
                log.flush()
                self.manager.t_cmd_start()
                terminal = Terminal(verbose=False)
                from ..utils.watchdog import Watchdog, write_sentinel_health
                def _exec_unresp():
                    setattr(self, '_stall_killed', True)
                    terminal.terminate_process()
                    if url:
                        from ..utils.pool import record_unresponsive
                        if record_unresponsive(url):
                            print(f"[watchdog] executor not responsive (no output in {NO_OUTPUT_EXEC_S}s) "
                                  f"— server {url} unresponsive too many times, killed — will respawn on next dispatch", flush=True)
                        else:
                            print(f"[watchdog] executor not responsive (no output in {NO_OUTPUT_EXEC_S}s) "
                                  f"— use owrap f as fallback", flush=True)
                    else:
                        print(f"[watchdog] executor not responsive (no output in {NO_OUTPUT_EXEC_S}s) "
                              f"— use owrap f as fallback", flush=True)
                watchdog = Watchdog(
                    log_path=self.LOG_FILE,
                    kill_callback=lambda: (setattr(self, '_stall_killed', True), terminal.terminate_process()),
                    notify_callback=lambda state: (write_sentinel_health(sentinel, state), print(f"[watchdog] exec {state}", flush=True)),
                    kill_after_s=float(_read_config().get("exec_kill_s", EXEC_KILL_S)),
                    no_output_s=float(_read_config().get("no_output_exec_s", NO_OUTPUT_EXEC_S)),
                    unresponsive_callback=_exec_unresp,
                )
                watchdog.start()
                result = terminal.run(" ".join(cmd), capture_output=True, print_output=True, tee_file=log, cwd=str(get_workspace_path()))
                self.manager.t_cmd_end()
                rc = result.get("returncode", 1)
                if result.get("timed_out"):
                    print(format_failure_pointer("TIMED_OUT", session_id))
        finally:
            if watchdog:
                watchdog.stop()
            self._complete_sentinel(sentinel, rc)
            self.manager.complete_task(task_id)

        t = ""
        if self.manager._t_cmd_end is not None:
            t = f"opencode={self.manager._t_cmd_end - self.manager._t_cmd_start:.1f}s  total={self.manager._t_cmd_end - self.manager._t_invocation:.1f}s"
        status = "SUCCESS" if rc == 0 else "FAILED"
        if self.logger:
            self.logger.info("exec done rc=%d status=%s log=%s", rc, status, self.LOG_FILE)
        print(divider("[exec] completed"))
        print(f"status: {status}")
        print(f"exit: {rc}")
        print(f"log: {self.LOG_FILE}")
        if t:
            print(f"timing: {t}")
        area = os.environ.get("OWRAP_AREA", "")
        if not area and session_id:
            try:
                from ..utils.session_resolver import _parse, session_file
                d = _parse(session_file(session_id))
                area = d.get("area", "")
            except Exception:
                pass
        from ..utils.donow import check_donow
        donow_msg = check_donow(self.manager, session_id, area, self.manager.research, kind="exec")
        if donow_msg:
            print(f"\n{donow_msg}")
        try:
            with open(self.LOG_FILE, "a") as log2:
                log2.write(f"\n{divider('[exec] completed')}\n")
                log2.write(f"status: {status}\n")
                log2.write(f"exit: {rc}\n")
                log2.write(f"log: {self.LOG_FILE}\n")
                if t:
                    log2.write(f"timing: {t}\n")
        except Exception:
            pass
        self.manager.log_time(log_time)
        self._write_exec_log(plan_name)
        try:
            self.manager.append_context_recent(plan_name, rc, ctx=ctx_instr is not None, kind="exec")
            self.manager.refresh_context_plan(plan_path)
            self.manager.update_frequent_files()
        except Exception:
            pass
        if url:
            try:
                update_last_used(url)
            except Exception:
                pass
            if not getattr(self, '_stall_killed', False):
                try:
                    from ..utils.pool import record_responsive
                    record_responsive(url)
                except Exception:
                    pass
            try:
                from ..utils.pool import release_server
                release_server(url)
            except Exception:
                pass

        if rc != 0 and rc != 2:
            print(format_failure_pointer("TASK_FAILED", session_id))

        sys.exit(rc)


def main():
    parser = argparse.ArgumentParser(description="Execute the active plan via opencode")
    parser.add_argument("--log-time", action="store_true", help="Show the [timing] block (debugging/tests only)")
    args = parser.parse_args()
    manager = Manager()
    ExecRunner(manager).run(log_time=args.log_time)


if __name__ == "__main__":
    main()
