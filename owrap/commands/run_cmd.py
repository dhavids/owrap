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
from ..constants import (
    ANTI_SUMMARY_SUFFIX, MSG_KILL_S, TASK_KILL_S, TASK_HARD_TIMEOUT_S,
    LOG_WRAP_WIDTH, NO_OUTPUT_MSG_S, NO_OUTPUT_TASK_S, MSG_MAX_CHARS,
)
from ..utils.pool import _pool_active, pick_server, update_last_used
from ..utils.paths import (
    TASKS_DIR, RUNTIME_DIR, context_path, _read_config,
    get_agents_md_path, get_workspace_config, get_workspace_path,
    get_dispatch_model, format_failure_pointer, FALLBACK_TASK,
    session_msg_output_dir, session_task_output_dir,
    session_tasks_dir, session_precompact_dir,
)
from ..utils.snippet import extract_snippet, wrap_log_text, divider

_PLACEHOLDER_TAG_RE = re.compile(r'<([A-Za-z][\w-]*)>')


def _sanitize_placeholder_tags(text: str) -> str:
    """Rewrite bare placeholder tags like <Topic> to [Topic].

    A bare single-word angle-bracket tag with no closing counterpart causes
    the executor to hang producing zero output (confirmed via bisection).
    Only this narrow shape is rewritten — comparisons, generics, git conflict
    markers, and real HTML/XML snippets don't match and are left untouched.
    """
    return _PLACEHOLDER_TAG_RE.sub(r'[\1]', text)


class RunRunner(BaseRunner):
    """Runner for executing tasks and messages via opencode."""
    TASKS_DIR = TASKS_DIR
    FALLBACK_TASK = FALLBACK_TASK

    def __init__(
        self, manager, logger=None, allow_all=False,
        add_context=False, model=None, disablewd=False,
    ):
        super().__init__(manager, logger, allow_all)
        self.add_context = add_context
        self.model = model
        self.disablewd = disablewd

    def run(self, msg=None, msg_id=None, input_path=None, log_time=False, timeout=None):
        """Run a task or message, dispatching to the appropriate handler."""
        self._cleanup_recently_done()
        if self.logger:
            if msg is not None:
                self.logger.info(
                    "run msg=%.80r session=%s", msg,
                    self.manager.session_id or "none",
                )
            else:
                self.logger.info("run task session=%s", self.manager.session_id or "none")

        if _pool_active():
            try:
                if msg is not None:
                    url = pick_server("msg")
                else:
                    url = pick_server("task")
            except Exception:
                print(format_failure_pointer("NO_SERVER", self.manager.session_id))
                sys.exit(1)
        else:
            url = self.manager.ensure_running()

        if msg is not None:
            return self._run_msg(
                msg, url, log_time, msg_id=msg_id, timeout=timeout,
                disablewd=self.disablewd,
            )
        return self._run_task(
            url, input_path, log_time, timeout=timeout,
            disablewd=self.disablewd,
        )

    def _get_task_title(self, task_file: Path) -> str:
        stem = task_file.stem.replace('task', '')
        return extract_snippet(task_file, default=f"task{stem}")

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

    def _run_msg(
        self, msg, url, log_time, msg_id=None, timeout=None, disablewd=False,
    ):
        self._install_sigterm_handler()
        if msg == "-":
            import sys as _sys
            msg = _sys.stdin.read()
        _msg_sentinel_id = msg_id or f"fg_{int(time.time())}"
        session_msg_output_dir(self.manager.session_id).mkdir(parents=True, exist_ok=True)
        msg_log = (
            session_msg_output_dir(self.manager.session_id)
            / f"msg_{_msg_sentinel_id}.log"
        )
        if '\n' in msg:
            if self.logger:
                self.logger.error(
                    "run msg rejected: newlines not allowed in --msg session=%s",
                    self.manager.session_id or "none",
                )
            err = (
                "Error: --msg must not contain newlines — "
                "use a file task (write input.md, then `orun`)."
            )
            print(err)
            with open(msg_log, "w") as _lf:
                _lf.write(
                    f"[{datetime.now().isoformat()}] MSG START\n\n"
                    f"{err}\n\n"
                    f"[{datetime.now().isoformat()}] rc=1 crashed (rc=1)\n"
                )
            self._write_run_log(msg[:80], tag=f"[m:{msg_id}]" if msg_id else "")
            sys.exit(1)
        if len(msg) > MSG_MAX_CHARS:
            if self.logger:
                self.logger.error(
                    "run msg rejected: len=%d >%d session=%s",
                    len(msg), MSG_MAX_CHARS,
                    self.manager.session_id or "none",
                )
            err = (
                f"Error: --msg must be <= {MSG_MAX_CHARS} characters "
                f"(got {len(msg)}) — either shorten the message, or "
                f"switch to a file task (write input.md, then `orun`)."
            )
            print(err)
            with open(msg_log, "w") as _lf:
                _lf.write(
                    f"[{datetime.now().isoformat()}] MSG START\n\n"
                    f"{err}\n\n"
                    f"[{datetime.now().isoformat()}] rc=1 crashed (rc=1)\n"
                )
            self._write_run_log(msg[:80], tag=f"[m:{msg_id}]" if msg_id else "")
            sys.exit(1)
        if msg_id:
            print(f"[m:{msg_id}]", flush=True)
        sentinel = self._write_sentinel(
            _msg_sentinel_id, msg[:60], kind="msg",
            call_type="msg", url=url, output_path=msg_log,
        )
        _ctx_cfg = _read_config()
        cp = context_path(self.manager.session_id)
        ctx_injected = False
        original_msg = msg
        if (
            self.add_context
            and _ctx_cfg.get("context_enabled", True)
            and self.manager.session_id
            and cp.exists()
            and cp.stat().st_size > 0
        ):
            msg = f"First read {cp} for context, then: {msg}"
            ctx_injected = True
        msg += " " + ANTI_SUMMARY_SUFFIX
        exec_prompt = f"--executor {msg}"
        cmd = ["opencode", "run", "--thinking", "--dir", str(get_workspace_path())]
        if self.allow_all:
            cmd.append("--dangerously-skip-permissions")
        model = get_dispatch_model(_ctx_cfg, override=self.model, default_to_fast=True)
        if model:
            cmd.extend(["-m", model])
        if url:
            cmd.extend(["--attach", url])
        if not url:
            fallback_file = self.FALLBACK_TASK
            fallback_file.write_text(f"## Do\n\n{exec_prompt}\n")
            cmd.extend(["--", shlex.quote(f"--executor --taskf {fallback_file}")])
        else:
            cmd.extend(["--", shlex.quote(exec_prompt)])

        if self.logger:
            self.logger.debug("run msg cmd=%s", " ".join(cmd))
        MSG_TIMEOUT = timeout if timeout is not None else 180
        rc = 1
        timed_out = False
        infra_failure = False
        result = {}
        print(f"log: {msg_log}", flush=True)
        watchdog = None
        try:
            self.manager.t_cmd_start()
            with open(msg_log, "w") as tee:
                tee.write(
                    f"[{datetime.now().isoformat()}] MSG START\n\n"
                    f"{divider('INPUT')}\n\n"
                    f"{wrap_log_text(original_msg, LOG_WRAP_WIDTH)}\n\n"
                )
                tee.flush()
                tee.write(f"{divider('EXECUTOR OUTPUT')}\n")
                tee.write(f"[server: {url or 'direct'}]\n\n")
                tee.flush()
                terminal = Terminal(verbose=False)
                from ..utils.watchdog import Watchdog
                def _msg_stop():
                    setattr(self, '_stall_killed', True)
                    terminal.terminate_process()
                if not disablewd:
                    watchdog = Watchdog(
                        log_path=msg_log,
                        kind="msg",
                        sentinel_path=sentinel,
                        url=url,
                        kill_callback=_msg_stop,
                        kill_after_s=float(
                            _read_config().get("msg_kill_s", MSG_KILL_S),
                        ),
                        no_output_s=float(
                            _read_config().get("no_output_msg_s", NO_OUTPUT_MSG_S),
                        ),
                        unresponsive_callback=_msg_stop,
                    )
                    watchdog.start()
                else:
                    watchdog = None
                result = terminal.run(
                    " ".join(cmd), print_output=True, capture_output=True,
                    timeout=MSG_TIMEOUT, tee_file=tee, use_pty=True,
                    cwd=str(get_workspace_path()),
                )

            self.manager.t_cmd_end()
        except Exception as exc:
            self.manager.t_cmd_end()
            if self.logger:
                self.logger.error("run msg error: %s", exc)
        finally:
            if watchdog:
                watchdog.stop()
            rc = self._finish_dispatch(
                "orun --msg", result, watchdog, sentinel, msg_log,
                self.manager.session_id, MSG_TIMEOUT, 180,
            )
            timed_out = bool(result.get("timed_out"))
            infra_failure = rc == 1
            if self.logger:
                self.logger.info(
                    "run msg done msg=%.80r rc=%d%s", msg, rc,
                    " (timeout)" if timed_out else "",
                )
            _skip_recent_msg = "owrap sync" in original_msg
            if not _skip_recent_msg:
                self._write_run_log(
                    original_msg[:80],
                    tag=f"[m:{msg_id}]" if msg_id else "",
                )
                try:
                    self.manager.append_context_recent(
                        original_msg[:80], rc,
                        ctx=ctx_injected, kind="msg",
                    )
                    self.manager.update_frequent_files()
                except Exception:
                    pass
            self.manager.log_time(log_time)
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
        sys.exit(rc)

    def _run_task(
        self, url, input_path, log_time, timeout=None, disablewd=False,
    ):
        if input_path is None:
            input_path = self.manager.input_path

        # Generate task name and log path early so we can write to the log
        # on early-failure paths (owait watches the log file for mtime change).
        task_name = self.manager.next_task_name()
        self.manager.register_task(task_name, "task")
        if self.manager.session_id:
            tasks_dir = session_tasks_dir(self.manager.session_id)
        else:
            tasks_dir = self.TASKS_DIR
        session_task_output_dir(
            self.manager.session_id
        ).mkdir(parents=True, exist_ok=True)
        log_path = (
            session_task_output_dir(self.manager.session_id)
            / f"{task_name}.log"
        )

        if not input_path.exists() or input_path.stat().st_size == 0:
            err = "Error: input.md is empty or missing"
            print(err, file=sys.stderr)
            print(format_failure_pointer("INPUT_EMPTY", self.manager.session_id))
            with open(log_path, "w") as _lf:
                _lf.write(
                    f"[{datetime.now().isoformat()}] TASK {task_name} START\n\n"
                    f"{err}\n\n"
                    f"[{datetime.now().isoformat()}] rc=1 crashed (rc=1)\n"
                )
            self._write_run_log("input_empty", tag=f"[t:{task_name}]")
            sys.exit(1)

        content = _sanitize_placeholder_tags(input_path.read_text())
        _first_line = content.split("\n", 1)[0].strip()
        _skip_recent = (
            _first_line in ("# Update Context", "# Update Protocol")
            or _first_line.startswith("## Update Context (pre-compaction)")
            or _first_line.startswith("## Update Protocol (pre-compaction)")
            or _first_line in (
                "# Sync Task — re-apply staged templates to project files",
            )
            or (input_path is not None and "sync" in input_path.name)
        )

        if url:
            task_file = tasks_dir / f'{task_name}.md'
            _ctx_cfg = _read_config()
            cp = context_path(self.manager.session_id)
            ctx_injected = False
            executor_md = get_agents_md_path()
            if (
                _ctx_cfg.get("context_enabled", True)
                and self.manager.session_id
                and cp.exists()
                and cp.stat().st_size > 0
            ):
                if executor_md and executor_md.exists():
                    content = (
                        f"## Context\nFirst read {executor_md}, then read "
                        f"{cp} before starting this task.\n\n" + content
                    )
                else:
                    content = (
                        f"## Context\nFirst read {cp} before starting "
                        f"this task.\n\n" + content
                    )
                ctx_injected = True
            content += " " + ANTI_SUMMARY_SUFFIX
            tasks_dir.mkdir(parents=True, exist_ok=True)
            task_file.write_text(content)
            input_path.write_text("")

            _is_precompact = (
                input_path is not None
                and input_path.name == "input_precompact.md"
            )
            _is_context = _first_line in ("# Context Update", "# Update Context")
            _is_updr = _first_line in ("# Update Protocol",)
            _is_sync = (
                _first_line in (
                    "# Sync Task — re-apply staged templates to project files",
                )
                or (input_path is not None and "sync" in input_path.name)
            )
            if _is_precompact and self.manager.session_id:
                _pcdir = session_precompact_dir(self.manager.session_id)
                _pcdir.mkdir(parents=True, exist_ok=True)
                log_path = _pcdir / "precompact.log"

            cmd = ["opencode", "run", "--thinking", "--dir", str(get_workspace_path())]
            if self.allow_all:
                cmd.append("--dangerously-skip-permissions")
            task_model = get_dispatch_model(
                _ctx_cfg, override=self.model, default_to_fast=False,
            )
            if task_model:
                cmd.extend(["-m", task_model])
            cmd.extend(["--attach", url])
            cmd.extend([
                "--", shlex.quote(
                    f"--executor --task {task_file} {ANTI_SUMMARY_SUFFIX}",
                ),
            ])

            title = self._get_task_title(task_file)
            if _is_precompact:
                _task_kind = "precompact"
            elif _is_context:
                _task_kind = "context"
            elif _is_updr:
                _task_kind = "updr"
            elif _is_sync:
                _task_kind = "sync"
            else:
                _task_kind = "task"
            sentinel = self._write_sentinel(
                task_name, title, kind=_task_kind,
                call_type="task", url=url, output_path=log_path,
            )
            self._install_sigterm_handler()
            if self.logger:
                self.logger.info(
                    "run task_name=%s title=%.60r session=%s",
                    task_name, title,
                    self.manager.session_id or "none",
                )
                self.logger.debug("run task cmd=%s", " ".join(cmd))
            print(f"[t:{task_name}]", flush=True)
            print(f"log: {log_path}", flush=True)

            rc = 1
            timed_out = False
            infra_failure = False
            result = {}
            watchdog = None
            hard_timeout = timeout if timeout is not None else TASK_HARD_TIMEOUT_S
            try:
                with open(log_path, "w") as log:
                    log.write(
                        f"[{datetime.now().isoformat()}] TASK {task_name} START\n\n"
                    )
                    log.write(f"{divider('INPUT')}\n\nTask file: {task_file}\n\n")
                    log.flush()
                    log.write(f"{divider('EXECUTOR OUTPUT')}\n")
                    log.flush()
                    self.manager.t_cmd_start()
                    terminal = Terminal(verbose=False)
                    from ..utils.watchdog import Watchdog
                    def _task_stop():
                        setattr(self, '_stall_killed', True)
                        terminal.terminate_process()
                    if not disablewd:
                        watchdog = Watchdog(
                            log_path=log_path,
                            kind="task",
                            sentinel_path=sentinel,
                            url=url,
                            kill_callback=_task_stop,
                            kill_after_s=float(
                                _read_config().get("task_kill_s", TASK_KILL_S),
                            ),
                            no_output_s=float(
                                _read_config().get(
                                    "no_output_task_s", NO_OUTPUT_TASK_S,
                                ),
                            ),
                            unresponsive_callback=_task_stop,
                        )
                        watchdog.start()
                    else:
                        watchdog = None
                    result = terminal.run(
                        " ".join(cmd), capture_output=True, print_output=True,
                        tee_file=log, cwd=str(get_workspace_path()),
                        timeout=hard_timeout, use_pty=True,
                    )
                    self.manager.t_cmd_end()
            except Exception as exc:
                self.manager.t_cmd_end()
                if self.logger:
                    self.logger.error("run task_name=%s error: %s", task_name, exc)
            finally:
                if watchdog:
                    watchdog.stop()
                rc = self._finish_dispatch(
                    "orun --input", result, watchdog, sentinel, log_path,
                    self.manager.session_id, hard_timeout, TASK_HARD_TIMEOUT_S,
                )
                timed_out = bool(result.get("timed_out"))
                infra_failure = rc == 1
                self.manager.complete_task(task_name)
                task_file.unlink(missing_ok=True)
                if self.logger:
                    self.logger.info(
                        "run task_name=%s done rc=%d log=%s%s",
                        task_name, rc, log_path,
                        " (timeout)" if timed_out else "",
                    )
                t = ""
                if self.manager._t_cmd_end is not None:
                    t = (
                        f"opencode="
                        f"{self.manager._t_cmd_end - self.manager._t_cmd_start:.1f}s"
                        f"  total="
                        f"{self.manager._t_cmd_end - self.manager._t_invocation:.1f}s"
                    )
                status = "SUCCESS" if rc == 0 else "FAILED"
                print(divider(f"[{task_name}] completed"))
                print(f"status: {status}")
                print(f"exit: {rc}")
                print(f"log: {log_path}")
                if t:
                    print(f"timing: {t}")
                area = os.environ.get("OWRAP_AREA", "")
                if not area and self.manager.session_id:
                    try:
                        from ..utils.session_resolver import _parse, session_file
                        d = _parse(session_file(self.manager.session_id))
                        area = d.get("area", "")
                    except Exception:
                        pass
                from ..utils.donow import check_donow
                donow_msg = check_donow(
                    self.manager, self.manager.session_id, area,
                    self.manager.research, kind=_task_kind,
                    input_path=input_path,
                )
                if donow_msg:
                    print(f"\n{donow_msg}")
                if not _is_precompact:
                    try:
                        with open(log_path, 'a') as log2:
                            log2.write(f'\n{divider(f"[{task_name}] completed")}\n')
                            log2.write(f'status: {status}\n')
                            log2.write(f'exit: {rc}\n')
                            log2.write(f'log: {log_path}\n')
                            if t:
                                log2.write(f"timing: {t}\n")
                    except Exception:
                        pass
                self.manager.log_time(log_time)
                self._write_run_log(title, tag=f"[t:{task_name}]")
                try:
                    if not _skip_recent:
                        self.manager.append_context_recent(title, rc, ctx=ctx_injected)
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
                if rc == 3:
                    print(
                        f"TASK_FAILED (rc={rc}) — rewrite input.md (get its path via "
                        f"`owrap get input`) before redispatching via orun."
                    )
        else:
            fallback_file = self.FALLBACK_TASK
            _ctx_cfg_fb = _read_config()
            cp = context_path(self.manager.session_id)
            ctx_injected_fb = False
            executor_md_fb = get_agents_md_path()
            if (
                _ctx_cfg_fb.get("context_enabled", True)
                and self.manager.session_id
                and cp.exists()
                and cp.stat().st_size > 0
            ):
                if executor_md_fb and executor_md_fb.exists():
                    content = (
                        f"## Context\nFirst read {executor_md_fb}, then read "
                        f"{cp} before starting this task.\n\n" + content
                    )
                else:
                    content = (
                        f"## Context\nFirst read {cp} before starting "
                        f"this task.\n\n" + content
                    )
                ctx_injected_fb = True
            content += " " + ANTI_SUMMARY_SUFFIX
            fallback_file.write_text(f"--executor\n\n{content}")
            input_path.write_text("")

            cmd = ["opencode", "run", "--thinking"]
            if self.allow_all:
                cmd.append("--dangerously-skip-permissions")
            fb_model = get_dispatch_model(
                _ctx_cfg_fb, override=self.model, default_to_fast=False,
            )
            if fb_model:
                cmd.extend(["-m", fb_model])
            cmd.extend(["--", shlex.quote(f"--executor --taskf {fallback_file}")])

            title = self._get_task_title(fallback_file)
            self.manager.t_cmd_start()
            Terminal(verbose=False).run(" ".join(cmd), print_output=True)
            self.manager.t_cmd_end()
            rc = 0
            self.manager.log_time(log_time)
            self._write_run_log(title, tag=f"[t:0]")
            try:
                if not _skip_recent:
                    self.manager.append_context_recent(
                        title, rc, ctx=ctx_injected_fb,
                    )
                    self.manager.update_frequent_files()
            except Exception:
                pass

        sys.exit(rc)


def main():
    parser = argparse.ArgumentParser(description="Run a task via opencode task")
    parser.add_argument(
        "--msg", type=str, default=None,
        help="Single-line message for task mode",
    )
    parser.add_argument(
        "--id", "-i", type=str, default=None,
        help="Msg ID for parallel tracking",
    )
    parser.add_argument(
        "--input", type=str, default=None,
        help="Input file path (default: owrap/docs/run/input_<session_id>.md)",
    )
    parser.add_argument(
        "--log-time", action="store_true",
        help="Show the [timing] block (debugging/tests only)",
    )
    parser.add_argument(
        "--add-context", action="store_true",
        help="Tell the msg task to read context.md before responding",
    )
    parser.add_argument("--model", "-m", type=str, default=None, help="Model override")
    args = parser.parse_args()
    manager = Manager()
    runner = RunRunner(
        manager, add_context=args.add_context, model=args.model,
    )
    runner.run(
        msg=args.msg, msg_id=args.id,
        input_path=Path(args.input) if args.input else None,
        log_time=args.log_time,
    )


if __name__ == "__main__":
    main()
