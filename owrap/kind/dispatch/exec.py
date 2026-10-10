import shlex
import sys
from datetime import datetime
from pathlib import Path

from . import Dispatch
from ...dispatch import work
from ...dispatch.manager import Manager
from ...session.donow import check_donow
from ...utils.constants import (
    ANTI_SUMMARY_SUFFIX, EXEC_HARD_TIMEOUT_S, EXEC_KILL_S,
    INFRA_FAILURE_EXEC_S, NO_OUTPUT_EXEC_S,
)
from ...utils.dispatch.pool import (
    _pool_active, pick_server, record_responsive, release_server,
    update_last_used,
)
from ...utils.dispatch.terminal import Terminal
from ...utils.dispatch.watchdog import Watchdog
from ...utils.parser.snippet import divider, extract_snippet
from ...utils.paths import (
    context_path, format_failure_pointer, get_agents_md_path,
    get_dispatch_model, get_plan_path, get_workspace_path, session_exec_output_path,
    _read_config,
)


class Exec(Dispatch):
    """
    Dispatches the session's active plan to opencode -- the `oexec`
    command. Unlike `read`, this is the long-running "work through
    the plan" call: a much longer watchdog/timeout, and on success it
    also refreshes the session's own context-plan/frequent-files
    state, not just its own sentinel/log. Overrides `start` directly
    for the same reason `Read` does.
    """

    kind = "exec"

    usage = {
        "start": {
            "usage": "[--timeout <s>] [--no-watchdog]",
            "args": [],
            "examples": [""],
            "purpose": "Execute the active session plan",
            "group": "dispatch",
        },
        "get": {
            "usage": "<task_id>",
            "args": [("task_id", "an exec task's id (its session id)")],
            "examples": ["abc123"],
        },
    }


    # Public Methods

    def start(
        self, log_time: bool = False, timeout: float = None,
        no_watchdog: bool = False, model: str = None,
    ) -> None:
        """
        Send the session's active plan to opencode and block until
        it finishes.
        """
        manager = Manager()
        session_id = manager.session_id
        log_file = session_exec_output_path(session_id or "exec")
        print(f"log: {log_file}", flush=True)
        work.cleanup_recently_done()
        plan_path = get_plan_path(session_id) if session_id else None

        if _pool_active():
            try:
                url = pick_server("exec")
            except Exception:
                print(format_failure_pointer("NO_SERVER", session_id))
                sys.exit(1)
        else:
            url = manager.ensure_running()

        cmd = ["opencode", "run", "--thinking", "--dir", str(get_workspace_path())]
        if work.allow_all():
            cmd.append("--dangerously-skip-permissions")
        ctx_cfg = _read_config()
        exec_model = get_dispatch_model(ctx_cfg, override=model, default_to_fast=False)
        if exec_model:
            cmd.extend(["-m", exec_model])
        cp = context_path(session_id) if session_id else None
        ctx_instr = None
        executor_md = get_agents_md_path()
        if cp and work.should_inject_context(ctx_cfg, session_id, cp):
            ctx_instr = work.context_prefix(cp, executor_md)
        plan_str = str(plan_path) if plan_path else ""
        exec_msg = f"--executor --exec {plan_str}".strip()
        exec_msg += " " + ANTI_SUMMARY_SUFFIX
        if url:
            cmd.extend(["--attach", url])
            prompt = f"{ctx_instr}{exec_msg}" if ctx_instr else exec_msg
            cmd.extend(["--", shlex.quote(prompt)])
        else:
            execf_msg = f"--executor --execf {plan_str}".strip()
            fb_prompt = f"{ctx_instr}{execf_msg}" if ctx_instr else execf_msg
            fb_prompt += " " + ANTI_SUMMARY_SUFFIX
            cmd.extend(["--", shlex.quote(fb_prompt)])

        plan_name = self._active_plan_name(manager, plan_path)

        log_file.parent.mkdir(parents=True, exist_ok=True)
        if log_file.exists():
            try:
                log_file.unlink()
            except OSError:
                ts = datetime.now().strftime("%H%M%S")
                log_file = log_file.parent / f"{log_file.stem}_{ts}{log_file.suffix}"

        task_id = session_id or "exec"
        manager.register_task(task_id, "exec")
        sentinel = work.write_sentinel(
            session_id, task_id, plan_name[:60],
            kind="exec", call_type="exec", url=url, output_path=log_file,
        )
        state = work.new_signal_state()
        work.install_sigterm_handler(state)
        rc = 1
        result = {}
        watchdog = None
        hard_timeout = timeout if timeout is not None else EXEC_HARD_TIMEOUT_S
        try:
            with open(log_file, "w") as log:
                log.write(f"[{datetime.now().isoformat()}] EXEC SESSION START\n\n")
                log.write(f"{divider('INPUT')}\n\nPlan file: {plan_str}\n\n")
                log.flush()
                log.write(f"{divider('EXECUTOR OUTPUT')}\n")
                log.flush()
                manager.t_cmd_start()
                terminal = Terminal(verbose=False)

                def _exec_stop():
                    state["stall_killed"] = True
                    terminal.terminate_process()
                if not no_watchdog:
                    watchdog = Watchdog(
                        log_path=log_file, kind="exec", sentinel_path=sentinel,
                        url=url, kill_callback=_exec_stop,
                        kill_after_s=float(ctx_cfg.get("exec_kill_s", EXEC_KILL_S)),
                        no_output_s=float(
                            ctx_cfg.get("no_output_exec_s", NO_OUTPUT_EXEC_S),
                        ),
                        infra_failure_s=float(
                            ctx_cfg.get("infra_failure_exec_s", INFRA_FAILURE_EXEC_S),
                        ),
                        unresponsive_callback=_exec_stop,
                    )
                    watchdog.start()
                result = terminal.run(
                    " ".join(cmd), capture_output=True, print_output=True,
                    tee_file=log, cwd=str(get_workspace_path()),
                    timeout=hard_timeout, use_pty=True,
                )
                manager.t_cmd_end()
        finally:
            if watchdog:
                watchdog.stop()
            rc = work.finish_dispatch(
                "oexec", result, watchdog, sentinel, log_file,
                hard_timeout, EXEC_HARD_TIMEOUT_S, state=state,
            )
            manager.complete_task(task_id)

        timing = ""
        if manager._t_cmd_end is not None:
            elapsed = manager._t_cmd_end - manager._t_cmd_start
            total = manager._t_cmd_end - manager._t_invocation
            timing = f"opencode={elapsed:.1f}s  total={total:.1f}s"
        status = "SUCCESS" if rc == 0 else "FAILED"
        print(divider("[exec] completed"))
        print(f"status: {status}")
        print(f"exit: {rc}")
        print(f"log: {log_file}")
        if timing:
            print(f"timing: {timing}")
        donow_msg = check_donow(session_id) if session_id else None
        if donow_msg:
            print(f"\n{donow_msg}")
        try:
            with open(log_file, "a") as log2:
                log2.write(f"\n{divider('[exec] completed')}\n")
                log2.write(f"status: {status}\n")
                log2.write(f"exit: {rc}\n")
                log2.write(f"log: {log_file}\n")
                if timing:
                    log2.write(f"timing: {timing}\n")
        except Exception:
            pass
        manager.log_time(log_time)
        work.prepend_log_entry(manager.exec_log_path, plan_name)
        try:
            manager.append_context_recent(
                plan_name, rc, ctx=ctx_instr is not None, kind="exec",
            )
            manager.refresh_context_plan(plan_path)
            manager.update_frequent_files()
        except Exception:
            pass
        if url:
            try:
                update_last_used(url)
            except Exception:
                pass
            if not state["stall_killed"]:
                try:
                    record_responsive(url)
                except Exception:
                    pass
            try:
                release_server(url)
            except Exception:
                pass
        sys.exit(rc)


    # Private Methods

    def _active_plan_name(self, manager, plan_path: Path | None = None) -> str:
        if plan_path is None:
            plan_path = (
                get_plan_path(manager.session_id) if manager.session_id else None
            )
        if plan_path is None:
            return "exec"
        return extract_snippet(plan_path, default="exec")
