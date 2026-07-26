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
from ..constants import ANTI_SUMMARY_SUFFIX, MSG_KILL_S, TASK_KILL_S, LOG_WRAP_WIDTH, NO_OUTPUT_MSG_S, NO_OUTPUT_TASK_S, MSG_MAX_CHARS
from ..utils.pool import _pool_active, pick_server, update_last_used
from ..utils.paths import TASKS_DIR, RUNTIME_DIR, context_path, _read_config, get_agents_md_path, get_workspace_config, get_workspace_path, format_failure_pointer, FALLBACK_TASK, session_msg_output_dir, session_task_output_dir, session_tasks_dir, session_precompact_dir
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
    TASKS_DIR = TASKS_DIR
    FALLBACK_TASK = FALLBACK_TASK

    def __init__(self, manager, logger=None, allow_all=False, add_context=False, model=None):
        super().__init__(manager, logger, allow_all)
        self.add_context = add_context
        self.model = model

    def _get_task_title(self, task_file: Path) -> str:
        return extract_snippet(task_file, default=f"task{task_file.stem.replace('task', '')}")

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

    def run(self, msg=None, msg_id=None, input_path=None, log_time=False, timeout=None):
        self._cleanup_recently_done()
        if self.logger:
            if msg is not None:
                self.logger.info("run msg=%.80r session=%s", msg, self.manager.session_id or "none")
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
            return self._run_msg(msg, url, log_time, msg_id=msg_id, timeout=timeout)
        return self._run_task(url, input_path, log_time)

    def _run_msg(self, msg, url, log_time, msg_id=None, timeout=None):
        self._install_sigterm_handler()
        if msg == "-":
            import sys as _sys
            msg = _sys.stdin.read()
        if len(msg) > MSG_MAX_CHARS:
            if self.logger:
                self.logger.error("run msg rejected: len=%d >%d session=%s", len(msg), MSG_MAX_CHARS, self.manager.session_id or "none")
            print(
                f"Error: --msg must be <= {MSG_MAX_CHARS} characters (got {len(msg)}) — "
                f"either shorten the message, or switch to a file task "
                f"(write input.md, then `orun`)."
            )
            sys.exit(1)
        msg = _sanitize_placeholder_tags(msg)

        if msg_id:
            print(f"[m:{msg_id}]", flush=True)
        _msg_sentinel_id = msg_id or f"fg_{int(time.time())}"
        _msg_output_path = session_msg_output_dir(self.manager.session_id) / f"msg_{_msg_sentinel_id}.log"
        sentinel = self._write_sentinel(_msg_sentinel_id, msg[:60], kind="msg", call_type="msg", url=url, output_path=_msg_output_path)
        _ctx_cfg = _read_config()
        cp = context_path(self.manager.session_id)
        ctx_injected = False
        original_msg = msg
        if self.add_context and _ctx_cfg.get("context_enabled", True) and self.manager.session_id and cp.exists() and cp.stat().st_size > 0:
            msg = f"First read {cp} for context, then: {msg}"
            ctx_injected = True
        msg += " " + ANTI_SUMMARY_SUFFIX
        exec_prompt = msg
        cmd = ["opencode", "run", "--thinking", "--dir", str(get_workspace_path())]
        if self.allow_all:
            cmd.append("--dangerously-skip-permissions")
        if self.model:
            cmd.extend(["-m", self.model])
        else:
            fast_model = _ctx_cfg.get("fast_model")
            if not fast_model:
                ws_name = _ctx_cfg.get("default_workspace", "")
                if ws_name:
                    fast_model = get_workspace_config(ws_name).get("fast_model")
            if fast_model:
                cmd.extend(["-m", fast_model])
        if url:
            cmd.extend(["--attach", url])
        if not url:
            fallback_file = self.FALLBACK_TASK
            fallback_file.write_text(f"## Do\n\n{exec_prompt}\n")
            cmd.extend(["--", "--taskf", shlex.quote(str(fallback_file))])
        else:
            cmd.extend(["--", shlex.quote(exec_prompt)])

        if self.logger:
            self.logger.debug("run msg cmd=%s", " ".join(cmd))
        MSG_TIMEOUT = timeout if timeout is not None else 180
        rc = 1
        timed_out = False
        session_msg_output_dir(self.manager.session_id).mkdir(parents=True, exist_ok=True)
        msg_log = session_msg_output_dir(self.manager.session_id) / f"msg_{_msg_sentinel_id}.log"
        print(f"log: {msg_log}", flush=True)
        watchdog = None
        try:
            self.manager.t_cmd_start()
            with open(msg_log, "w") as tee:
                tee.write(f"[{datetime.now().isoformat()}] MSG START\n\n{divider('INPUT')}\n\n{wrap_log_text(original_msg, LOG_WRAP_WIDTH)}\n\n")
                tee.flush()
                tee.write(f"{divider('EXECUTOR OUTPUT')}\n")
                tee.write(f"[server: {url or 'direct'}]\n\n")
                tee.flush()
                terminal = Terminal(verbose=False)
                from ..utils.watchdog import Watchdog, write_sentinel_health
                def _msg_unresp():
                    setattr(self, '_stall_killed', True)
                    terminal.terminate_process()
                    if url:
                        from ..utils.pool import record_unresponsive
                        if record_unresponsive(url):
                            print(f"[watchdog] executor not responsive (no output in {NO_OUTPUT_MSG_S}s) "
                                  f"— server {url} unresponsive too many times, killed — will respawn on next dispatch", flush=True)
                        else:
                            print(f"[watchdog] executor not responsive (no output in {NO_OUTPUT_MSG_S}s) "
                                  f"— use owrap f as fallback", flush=True)
                    else:
                        print(f"[watchdog] executor not responsive (no output in {NO_OUTPUT_MSG_S}s) "
                              f"— use owrap f as fallback", flush=True)
                watchdog = Watchdog(
                    log_path=msg_log,
                    kill_callback=lambda: (setattr(self, '_stall_killed', True), terminal.terminate_process()),
                    notify_callback=lambda state: (write_sentinel_health(sentinel, state), print(f"[watchdog] msg {state}", flush=True)),
                    kill_after_s=float(_read_config().get("msg_kill_s", MSG_KILL_S)),
                    no_output_s=float(_read_config().get("no_output_msg_s", NO_OUTPUT_MSG_S)),
                    unresponsive_callback=_msg_unresp,
                )
                watchdog.start()
                result = terminal.run(
                    " ".join(cmd), print_output=True, capture_output=True,
                    timeout=MSG_TIMEOUT, tee_file=tee, use_pty=True,
                    cwd=str(get_workspace_path()),
                )

            self.manager.t_cmd_end()
            if result.get("timed_out"):
                timed_out = True
                partial = (result.get("stdout") or "").strip()
                chars = len(partial)
                print(flush=True)
                print(f"[orun --msg] timed out after {MSG_TIMEOUT}s ({chars} chars captured)", flush=True)
                print(f"  rerun with -t <seconds> to extend (default: 180s)", flush=True)
                print(format_failure_pointer("TIMED_OUT", self.manager.session_id))
                rc = 2
            else:
                rc = result.get("returncode", 1)
        except Exception as exc:
            self.manager.t_cmd_end()
            if self.logger:
                self.logger.error("run msg error: %s", exc)
        finally:
            if watchdog:
                watchdog.stop()
            try:
                _reason = (
                    "timeout" if timed_out
                    else "watchdog (no output)" if getattr(self, '_stall_killed', False)
                    else ("ok" if rc == 0 else f"crashed (rc={rc})")
                )
                with open(msg_log, "a") as _lf:
                    _lf.write(f"\n{divider('RESULT')}\n[{datetime.now().isoformat()}] rc={rc} {_reason}\n")
            except Exception:
                pass
            self._complete_sentinel(sentinel, rc, timed_out=timed_out)
            if self.logger:
                self.logger.info("run msg done msg=%.80r rc=%d%s", msg, rc, " (timeout)" if timed_out else "")
            _skip_recent_msg = "owrap sync" in original_msg
            if not _skip_recent_msg:
                self._write_run_log(original_msg[:80], tag=f"[m:{msg_id}]" if msg_id else "")
                try:
                    self.manager.append_context_recent(original_msg[:80], rc, ctx=ctx_injected, kind="msg")
                    self.manager.update_frequent_files()
                except Exception:
                    pass
                if rc != 0:
                    try:
                        n_fail = self.manager.consecutive_msg_failures()
                        if n_fail >= 2:
                            print(
                                f"[owrap] {n_fail} consecutive orun --msg failures "
                                f"this session — stop retrying this msg as-is. "
                                f"Switch to a file task (write input.md, then "
                                f"`orun`) or `owrap f`.",
                                flush=True,
                            )
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

    def _run_task(self, url, input_path, log_time):
        if input_path is None:
            input_path = self.manager.input_path

        if not input_path.exists() or input_path.stat().st_size == 0:
            print("Error: input.md is empty or missing", file=sys.stderr)
            print(format_failure_pointer("INPUT_EMPTY", self.manager.session_id))
            sys.exit(1)

        content = _sanitize_placeholder_tags(input_path.read_text())
        _first_line = content.split("\n", 1)[0].strip()
        _skip_recent = (
            _first_line in ("# Update Context", "# Update Protocol")
            or _first_line.startswith("## Update Context (pre-compaction)")
            or _first_line.startswith("## Update Protocol (pre-compaction)")
            or _first_line in ("# Sync Task — re-apply staged templates to project files",)
            or (input_path is not None and "sync" in input_path.name)
        )

        if url:
            task_name = self.manager.next_task_name()
            self.manager.register_task(task_name, "task")
            tasks_dir = session_tasks_dir(self.manager.session_id) if self.manager.session_id else self.TASKS_DIR
            task_file = tasks_dir / f'{task_name}.md'
            _ctx_cfg = _read_config()
            cp = context_path(self.manager.session_id)
            ctx_injected = False
            executor_md = get_agents_md_path()
            if _ctx_cfg.get("context_enabled", True) and self.manager.session_id and cp.exists() and cp.stat().st_size > 0:
                if executor_md and executor_md.exists():
                    content = f"## Context\nFirst read {executor_md}, then read {cp} before starting this task.\n\n" + content
                else:
                    content = f"## Context\nFirst read {cp} before starting this task.\n\n" + content
                ctx_injected = True
            content += " " + ANTI_SUMMARY_SUFFIX
            tasks_dir.mkdir(parents=True, exist_ok=True)
            task_file.write_text(content)
            input_path.write_text("")

            _is_precompact = input_path is not None and input_path.name == "input_precompact.md"
            _is_context = _first_line in ("# Context Update", "# Update Context")
            _is_updr = _first_line in ("# Update Protocol",)
            _is_sync = (
                _first_line in ("# Sync Task — re-apply staged templates to project files",)
                or (input_path is not None and "sync" in input_path.name)
            )
            if _is_precompact and self.manager.session_id:
                _pcdir = session_precompact_dir(self.manager.session_id)
                _pcdir.mkdir(parents=True, exist_ok=True)
                log_path = _pcdir / "precompact.log"
            else:
                session_task_output_dir(self.manager.session_id).mkdir(parents=True, exist_ok=True)
                log_path = session_task_output_dir(self.manager.session_id) / f"{task_name}.log"

            cmd = ["opencode", "run", "--thinking", "--dir", str(get_workspace_path())]
            if self.allow_all:
                cmd.append("--dangerously-skip-permissions")
            cmd.extend(["--attach", url])
            cmd.extend(["--", shlex.quote(f"--task {task_file} {ANTI_SUMMARY_SUFFIX}")])

            title = self._get_task_title(task_file)
            _task_kind = "precompact" if _is_precompact else ("context" if _is_context else ("updr" if _is_updr else ("sync" if _is_sync else "task")))
            sentinel = self._write_sentinel(task_name, title, kind=_task_kind, call_type="task", url=url, output_path=log_path)
            self._install_sigterm_handler()
            if self.logger:
                self.logger.info("run task_name=%s title=%.60r session=%s", task_name, title, self.manager.session_id or "none")
                self.logger.debug("run task cmd=%s", " ".join(cmd))
            print(f"[t:{task_name}]", flush=True)
            print(f"log: {log_path}", flush=True)

            rc = 1
            timed_out = False
            watchdog = None
            try:
                with open(log_path, "w") as log:
                    log.write(f"[{datetime.now().isoformat()}] TASK {task_name} START\n\n")
                    log.write(f"{divider('INPUT')}\n\nTask file: {task_file}\n\n")
                    log.flush()
                    log.write(f"{divider('EXECUTOR OUTPUT')}\n")
                    log.flush()
                    self.manager.t_cmd_start()
                    terminal = Terminal(verbose=False)
                    from ..utils.watchdog import Watchdog, write_sentinel_health
                    def _task_unresp():
                        setattr(self, '_stall_killed', True)
                        terminal.terminate_process()
                        if url:
                            from ..utils.pool import record_unresponsive
                            if record_unresponsive(url):
                                print(f"[watchdog] executor not responsive (no output in {NO_OUTPUT_TASK_S}s) "
                                      f"— server {url} unresponsive too many times, killed — will respawn on next dispatch", flush=True)
                            else:
                                print(f"[watchdog] executor not responsive (no output in {NO_OUTPUT_TASK_S}s) "
                                      f"— use owrap f as fallback", flush=True)
                        else:
                            print(f"[watchdog] executor not responsive (no output in {NO_OUTPUT_TASK_S}s) "
                                  f"— use owrap f as fallback", flush=True)
                    watchdog = Watchdog(
                        log_path=log_path,
                        kill_callback=lambda: (setattr(self, '_stall_killed', True), terminal.terminate_process()),
                        notify_callback=lambda state: (write_sentinel_health(sentinel, state), print(f"[watchdog] task {state}", flush=True)),
                        kill_after_s=float(_read_config().get("task_kill_s", TASK_KILL_S)),
                        no_output_s=float(_read_config().get("no_output_task_s", NO_OUTPUT_TASK_S)),
                        unresponsive_callback=_task_unresp,
                    )
                    watchdog.start()
                    result = terminal.run(" ".join(cmd), capture_output=True, print_output=True, tee_file=log, cwd=str(get_workspace_path()))
                    self.manager.t_cmd_end()
                    if result.get("timed_out"):
                        timed_out = True
                        print(format_failure_pointer("TIMED_OUT", self.manager.session_id))
                    rc = result.get("returncode", 1)
            except Exception as exc:
                self.manager.t_cmd_end()
                if self.logger:
                    self.logger.error("run task_name=%s error: %s", task_name, exc)
            finally:
                if watchdog:
                    watchdog.stop()
                self._complete_sentinel(sentinel, rc, timed_out=timed_out)
                self.manager.complete_task(task_name)
                task_file.unlink(missing_ok=True)
                if self.logger:
                    self.logger.info("run task_name=%s done rc=%d log=%s%s", task_name, rc, log_path, " (timeout)" if timed_out else "")
                t = ""
                if self.manager._t_cmd_end is not None:
                    t = f"opencode={self.manager._t_cmd_end - self.manager._t_cmd_start:.1f}s  total={self.manager._t_cmd_end - self.manager._t_invocation:.1f}s"
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
                donow_msg = check_donow(self.manager, self.manager.session_id, area, self.manager.research, kind=_task_kind, input_path=input_path)
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
        else:
            fallback_file = self.FALLBACK_TASK
            _ctx_cfg_fb = _read_config()
            cp = context_path(self.manager.session_id)
            ctx_injected_fb = False
            executor_md_fb = get_agents_md_path()
            if _ctx_cfg_fb.get("context_enabled", True) and self.manager.session_id and cp.exists() and cp.stat().st_size > 0:
                if executor_md_fb and executor_md_fb.exists():
                    content = f"## Context\nFirst read {executor_md_fb}, then read {cp} before starting this task.\n\n" + content
                else:
                    content = f"## Context\nFirst read {cp} before starting this task.\n\n" + content
                ctx_injected_fb = True
            content += " " + ANTI_SUMMARY_SUFFIX
            fallback_file.write_text(content)
            input_path.write_text("")

            cmd = ["opencode", "run", "--thinking"]
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
            try:
                if not _skip_recent:
                    self.manager.append_context_recent(title, rc, ctx=ctx_injected_fb)
                    self.manager.update_frequent_files()
            except Exception:
                pass

        sys.exit(rc)


def main():
    parser = argparse.ArgumentParser(description="Run a task via opencode task")
    parser.add_argument("--msg", type=str, default=None, help="Single-line message for task mode")
    parser.add_argument("--id", "-i", type=str, default=None, help="Msg ID for parallel tracking")
    parser.add_argument("--input", type=str, default=None, help="Input file path (default: owrap/docs/run/input_<session_id>.md)")
    parser.add_argument("--log-time", action="store_true", help="Show the [timing] block (debugging/tests only)")
    parser.add_argument("--add-context", action="store_true", help="Tell the msg task to read context.md before responding")
    parser.add_argument("--model", "-m", type=str, default=None, help="Model override")
    args = parser.parse_args()
    manager = Manager()
    RunRunner(manager, add_context=args.add_context, model=args.model).run(msg=args.msg, msg_id=args.id,
                           input_path=Path(args.input) if args.input else None,
                            log_time=args.log_time)


if __name__ == "__main__":
    main()
