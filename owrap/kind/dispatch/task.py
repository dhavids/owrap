import json
import os
import re
import shlex
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

from . import Dispatch
from ...dispatch import work
from ...dispatch.manager import Manager
from ...utils.session.donow import check_donow
from ...utils.constants import (
    ANTI_SUMMARY_SUFFIX, INFRA_FAILURE_MSG_S, INFRA_FAILURE_TASK_S,
    LOG_WRAP_WIDTH, MSG_KILL_S, MSG_MAX_CHARS, NO_OUTPUT_MSG_S,
    NO_OUTPUT_TASK_S, TASK_HARD_TIMEOUT_S, TASK_KILL_S,
)
from ...utils.dispatch.pool import (
    _pool_active, pick_server, record_responsive, release_server,
    update_last_used,
)
from ...utils.dispatch.terminal import Terminal
from ...utils.dispatch.watchdog import Watchdog
from ...utils.parser.snippet import divider, extract_snippet, wrap_log_text
from ...utils.paths import (
    FALLBACK_TASK, RUNNING_DIR, TASKS_DIR, _read_config, context_path,
    format_failure_pointer, get_agents_md_path, get_dispatch_model,
    get_workspace_path, session_msg_output_dir, session_task_output_dir,
    session_tasks_dir,
)

_PLACEHOLDER_TAG_RE = re.compile(r'<([A-Za-z][\w-]*)>')


def _sanitize_placeholder_tags(text: str) -> str:
    """
    Rewrite bare placeholder tags like <Topic> to [Topic].

    A bare single-word angle-bracket tag with no closing counterpart causes
    the executor to hang producing zero output (confirmed via bisection).
    Only this narrow shape is rewritten -- comparisons, generics, git conflict
    markers, and real HTML/XML snippets don't match and are left untouched.
    """
    return _PLACEHOLDER_TAG_RE.sub(r'[\1]', text)


def _target_matches(target: str, kind: str, task_id: str) -> bool:
    """
    Check whether a target string (as given to `owrap task done`)
    selects a sentinel: a bare kind name selects any task of that kind,
    `<kind><id>` selects one task.
    """
    t = target.lower()
    if t == "exec":
        return kind == "exec"
    if t.startswith("task"):
        suffix = t[4:]
        return kind == "task" and (suffix == "" or task_id == suffix)
    if t.startswith("msg"):
        suffix = t[3:]
        return kind == "msg" and (suffix == "" or task_id == suffix)
    if t.startswith("agent"):
        suffix = t[5:]
        return kind == "agent" and (suffix == "" or task_id == suffix)
    return kind == t


class Task(Dispatch):
    """
    Act on whatever any `Dispatch` kind wrote to RUNNING_DIR; it
    dispatches nothing of its own. `done` aborts a running task and `get`
    reports any kind's task by id. `start` runs a single-line `--msg` call
    or a file task read from `input_path` (the `orun` command).
    """

    kind = "task"

    usage = {
        "start": {
            "usage": "[--msg <text>] [--id <id>] [--input <path>]",
            "args": [
                ("msg", "single-line message for task mode"),
                ("id", "msg id for parallel tracking"),
                ("input", "input file path (default: input_<session_id>.md)"),
            ],
            "examples": ["--msg 'summarise owrap/cli.py'", ""],
            "purpose": "Run one inline task, or dispatch a task file",
            "group": "dispatch",
        },
        "done": {
            "usage": "<target> [<session_id>]",
            "args": [
                ("target", "a bare kind ('exec'), kind+id ('msg123'), "
                           "or exact task_id to abort"),
                ("session_id", "scope to one session; defaults to the "
                               "attached session"),
            ],
            "examples": ["exec", "msg123", "task"],
        },
        "get": {
            "usage": "<task_id>",
            "args": [("task_id", "any dispatched task's id, any kind")],
            "examples": ["r_1234"],
        },
    }


    # Public Methods

    def start(
        self, msg: str = None, id: str = None, input: Path = None,
        log_time: bool = False, timeout: float = None, add_context: bool = False,
        model: str = None, disablewd: bool = False,
    ) -> None:
        """
        Dispatch a single-line `msg`, or (if `msg` is None) the file
        task read from `input` -- blocking until it finishes.
        """
        manager = Manager()
        work.cleanup_recently_done()

        if _pool_active():
            try:
                url = pick_server("msg" if msg is not None else "task")
            except Exception:
                print(format_failure_pointer("NO_SERVER", manager.session_id))
                sys.exit(1)
        else:
            url = manager.ensure_running()

        if msg is not None:
            self._start_msg(
                manager, msg, url, log_time, msg_id=id, timeout=timeout,
                add_context=add_context, model=model, disablewd=disablewd,
            )
        else:
            self._start_task(
                manager, url, input, log_time, timeout=timeout,
                model=model, disablewd=disablewd,
            )

    def done(self, target: str = None, session_id: str = None) -> None:
        """
        Abort every currently-running task matching `target`
        (optionally scoped to `session_id`): send SIGTERM, then
        complete its sentinel as aborted.
        """
        if target is None:
            self._usage("done")
        if session_id is None:
            session_id = os.environ.get("OWRAP_SESSION", "")

        if not RUNNING_DIR.exists():
            self._fail("no running jobs found")

        matched = []
        for f in sorted(RUNNING_DIR.iterdir()):
            if f.suffix != ".json":
                continue
            try:
                data = json.loads(f.read_text())
            except Exception:
                continue
            if session_id and data.get("session_id") != session_id:
                continue
            kind, task_id = data.get("kind", ""), str(data.get("task_id", ""))
            if _target_matches(target, kind, task_id):
                matched.append((f, data))

        if not matched:
            self._fail(
                f"no running job matching '{target}' for session {session_id}"
            )

        killed = 0
        for sentinel_path, data in matched:
            pid = data.get("pid")
            title = data.get("title", "?")
            label = f"{data.get('kind', 'task')}{data.get('task_id', '?')}"
            if not pid:
                print(f"  {label}: no PID in sentinel, skipping")
                continue
            try:
                os.kill(pid, 0)
            except OSError:
                print(f"  {label} (pid={pid}): already done")
                sentinel_path.unlink(missing_ok=True)
                continue
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                print(f"  {label} (pid={pid}): process not found")
                continue
            except PermissionError:
                print(f"  {label} (pid={pid}): permission denied")
                continue
            print(f"  sent SIGTERM to {label} (pid={pid})  \"{title}\"")
            killed += 1
            work.complete_sentinel(sentinel_path, 143, failure_kind="aborted")

        if killed == 0:
            self._fail("no job could be terminated")

    def get(self, task_id: str = None) -> None:
        """
        Report any dispatched task's status by id, whichever kind created
        it.
        """
        if task_id is None:
            self._usage("get")
        data = work.find_task(task_id)
        if data is None:
            self._fail(f"no task found with id {task_id}")
        print(work.format_task_status(data))


    # Private Methods

    def _get_task_title(self, task_file: Path) -> str:
        stem = task_file.stem.replace('task', '')
        return extract_snippet(task_file, default=f"task{stem}")

    def _start_msg(
        self, manager, msg, url, log_time, msg_id=None, timeout=None,
        add_context=False, model=None, disablewd=False,
    ) -> None:
        state = work.new_signal_state()
        work.install_sigterm_handler(state)
        if msg == "-":
            msg = sys.stdin.read()
        msg_sentinel_id = msg_id or f"fg_{int(time.time())}"
        session_msg_output_dir(manager.session_id).mkdir(parents=True, exist_ok=True)
        msg_log = (
            session_msg_output_dir(manager.session_id)
            / f"msg_{msg_sentinel_id}.log"
        )
        if '\n' in msg:
            err = (
                "Error: --msg must not contain newlines — "
                "use a file task (write input.md, then `orun`)."
            )
            print(err)
            with open(msg_log, "w") as lf:
                lf.write(
                    f"[{datetime.now().isoformat()}] MSG START\n\n"
                    f"{err}\n\n"
                    f"[{datetime.now().isoformat()}] rc=1 crashed (rc=1)\n"
                )
            work.prepend_log_entry(
                manager.run_log_path, msg[:80],
                tag=f"[m:{msg_id}]" if msg_id else "",
            )
            sys.exit(1)
        if len(msg) > MSG_MAX_CHARS:
            err = (
                f"Error: --msg must be <= {MSG_MAX_CHARS} characters "
                f"(got {len(msg)}) — either shorten the message, or "
                f"switch to a file task (write input.md, then `orun`)."
            )
            print(err)
            with open(msg_log, "w") as lf:
                lf.write(
                    f"[{datetime.now().isoformat()}] MSG START\n\n"
                    f"{err}\n\n"
                    f"[{datetime.now().isoformat()}] rc=1 crashed (rc=1)\n"
                )
            work.prepend_log_entry(
                manager.run_log_path, msg[:80],
                tag=f"[m:{msg_id}]" if msg_id else "",
            )
            sys.exit(1)
        if msg_id:
            print(f"[m:{msg_id}]", flush=True)
        sentinel = work.write_sentinel(
            manager.session_id, msg_sentinel_id, msg[:60], kind="msg",
            call_type="msg", url=url, output_path=msg_log,
        )
        ctx_cfg = _read_config()
        cp = context_path(manager.session_id)
        ctx_injected = False
        original_msg = msg
        if add_context and work.should_inject_context(ctx_cfg, manager.session_id, cp):
            msg = f"First read {cp} for context, then: {msg}"
            ctx_injected = True
        msg += " " + ANTI_SUMMARY_SUFFIX
        exec_prompt = f"--executor {msg}"
        cmd = ["opencode", "run", "--thinking", "--dir", str(get_workspace_path())]
        if work.allow_all():
            cmd.append("--dangerously-skip-permissions")
        dispatch_model = get_dispatch_model(ctx_cfg, override=model, default_to_fast=True)
        if dispatch_model:
            cmd.extend(["-m", dispatch_model])
        if url:
            cmd.extend(["--attach", url])
        if not url:
            fallback_file = FALLBACK_TASK
            fallback_file.write_text(f"## Do\n\n{exec_prompt}\n")
            cmd.extend(["--", shlex.quote(f"--executor --taskf {fallback_file}")])
        else:
            cmd.extend(["--", shlex.quote(exec_prompt)])

        msg_timeout = timeout if timeout is not None else 180
        result = {}
        print(f"log: {msg_log}", flush=True)
        watchdog = None
        try:
            manager.t_cmd_start()
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

                def _msg_stop():
                    state["stall_killed"] = True
                    terminal.terminate_process()
                if not disablewd:
                    watchdog = Watchdog(
                        log_path=msg_log, kind="msg", sentinel_path=sentinel,
                        url=url, kill_callback=_msg_stop,
                        kill_after_s=float(ctx_cfg.get("msg_kill_s", MSG_KILL_S)),
                        no_output_s=float(
                            ctx_cfg.get("no_output_msg_s", NO_OUTPUT_MSG_S),
                        ),
                        infra_failure_s=float(
                            ctx_cfg.get("infra_failure_msg_s", INFRA_FAILURE_MSG_S),
                        ),
                        unresponsive_callback=_msg_stop,
                    )
                    watchdog.start()
                result = terminal.run(
                    " ".join(cmd), print_output=True, capture_output=True,
                    timeout=msg_timeout, tee_file=tee, use_pty=True,
                    cwd=str(get_workspace_path()),
                )
            manager.t_cmd_end()
        except Exception:
            manager.t_cmd_end()
        finally:
            if watchdog:
                watchdog.stop()
            rc = work.finish_dispatch(
                "orun --msg", result, watchdog, sentinel, msg_log,
                msg_timeout, 180, state=state,
            )
            skip_recent_msg = "owrap sync" in original_msg
            if not skip_recent_msg:
                work.prepend_log_entry(
                    manager.run_log_path, original_msg[:80],
                    tag=f"[m:{msg_id}]" if msg_id else "",
                )
                try:
                    manager.append_context_recent(
                        original_msg[:80], rc, ctx=ctx_injected, kind="msg",
                    )
                    manager.update_frequent_files()
                except Exception:
                    pass
            manager.log_time(log_time)
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

    def _start_task(
        self, manager, url, input_path, log_time, timeout=None, model=None,
        disablewd=False,
    ) -> None:
        if input_path is None:
            input_path = manager.input_path

        task_name = manager.next_task_name()
        manager.register_task(task_name, "task")
        tasks_dir = (
            session_tasks_dir(manager.session_id) if manager.session_id
            else TASKS_DIR
        )
        session_task_output_dir(manager.session_id).mkdir(parents=True, exist_ok=True)
        log_path = session_task_output_dir(manager.session_id) / f"{task_name}.log"

        if not input_path.exists() or input_path.stat().st_size == 0:
            err = "Error: input.md is empty or missing"
            print(err, file=sys.stderr)
            print(format_failure_pointer("INPUT_EMPTY", manager.session_id))
            with open(log_path, "w") as lf:
                lf.write(
                    f"[{datetime.now().isoformat()}] TASK {task_name} START\n\n"
                    f"{err}\n\n"
                    f"[{datetime.now().isoformat()}] rc=1 crashed (rc=1)\n"
                )
            work.prepend_log_entry(
                manager.run_log_path, "input_empty", tag=f"[t:{task_name}]",
            )
            sys.exit(1)

        content = _sanitize_placeholder_tags(input_path.read_text())
        first_line = content.split("\n", 1)[0].strip()
        skip_recent = (
            first_line in ("# Update Context", "# Update Protocol")
            or first_line.startswith("## Update Context (pre-compaction)")
            or first_line.startswith("## Update Protocol (pre-compaction)")
            or first_line in (
                "# Sync Task — re-apply staged templates to project files",
            )
            or "sync" in input_path.name
        )

        if url:
            rc = self._start_task_attached(
                manager, url, input_path, tasks_dir, task_name, log_path,
                content, first_line, skip_recent, log_time, timeout, model,
                disablewd,
            )
        else:
            rc = self._start_task_fallback(
                manager, input_path, content, log_time, skip_recent, model,
            )
        sys.exit(rc)

    def _start_task_attached(
        self, manager, url, input_path, tasks_dir, task_name, log_path,
        content, first_line, skip_recent, log_time, timeout, model, disablewd,
    ) -> int:
        task_file = tasks_dir / f'{task_name}.md'
        ctx_cfg = _read_config()
        cp = context_path(manager.session_id)
        ctx_injected = False
        executor_md = get_agents_md_path()
        if work.should_inject_context(ctx_cfg, manager.session_id, cp):
            content = work.context_block(cp, executor_md) + content
            ctx_injected = True
        content += " " + ANTI_SUMMARY_SUFFIX
        tasks_dir.mkdir(parents=True, exist_ok=True)
        task_file.write_text(content)
        input_path.write_text("")

        if first_line in ("# Context Update", "# Update Context"):
            task_kind = "context"
        elif first_line in ("# Update Protocol",):
            task_kind = "updr"
        elif skip_recent and "sync" in input_path.name:
            task_kind = "sync"
        else:
            task_kind = "task"

        cmd = ["opencode", "run", "--thinking", "--dir", str(get_workspace_path())]
        if work.allow_all():
            cmd.append("--dangerously-skip-permissions")
        task_model = get_dispatch_model(ctx_cfg, override=model, default_to_fast=False)
        if task_model:
            cmd.extend(["-m", task_model])
        cmd.extend(["--attach", url])
        cmd.extend([
            "--", shlex.quote(f"--executor --task {task_file} {ANTI_SUMMARY_SUFFIX}"),
        ])

        title = self._get_task_title(task_file)
        sentinel = work.write_sentinel(
            manager.session_id, task_name, title, kind=task_kind,
            call_type="task", url=url, output_path=log_path,
        )
        state = work.new_signal_state()
        work.install_sigterm_handler(state)
        print(f"[t:{task_name}]", flush=True)
        print(f"log: {log_path}", flush=True)

        result = {}
        watchdog = None
        hard_timeout = timeout if timeout is not None else TASK_HARD_TIMEOUT_S
        try:
            with open(log_path, "w") as log:
                log.write(f"[{datetime.now().isoformat()}] TASK {task_name} START\n\n")
                log.write(f"{divider('INPUT')}\n\nTask file: {task_file}\n\n")
                log.flush()
                log.write(f"{divider('EXECUTOR OUTPUT')}\n")
                log.flush()
                manager.t_cmd_start()
                terminal = Terminal(verbose=False)

                def _task_stop():
                    state["stall_killed"] = True
                    terminal.terminate_process()
                if not disablewd:
                    watchdog = Watchdog(
                        log_path=log_path, kind="task", sentinel_path=sentinel,
                        url=url, kill_callback=_task_stop,
                        kill_after_s=float(ctx_cfg.get("task_kill_s", TASK_KILL_S)),
                        no_output_s=float(
                            ctx_cfg.get("no_output_task_s", NO_OUTPUT_TASK_S),
                        ),
                        infra_failure_s=float(
                            ctx_cfg.get("infra_failure_task_s", INFRA_FAILURE_TASK_S),
                        ),
                        unresponsive_callback=_task_stop,
                    )
                    watchdog.start()
                result = terminal.run(
                    " ".join(cmd), capture_output=True, print_output=True,
                    tee_file=log, cwd=str(get_workspace_path()),
                    timeout=hard_timeout, use_pty=True,
                )
                manager.t_cmd_end()
        except Exception:
            manager.t_cmd_end()
        finally:
            if watchdog:
                watchdog.stop()
            rc = work.finish_dispatch(
                "orun --input", result, watchdog, sentinel, log_path,
                hard_timeout, TASK_HARD_TIMEOUT_S, state=state,
            )
            manager.complete_task(task_name)
            task_file.unlink(missing_ok=True)
            t = ""
            if manager._t_cmd_end is not None:
                t = (
                    f"opencode={manager._t_cmd_end - manager._t_cmd_start:.1f}s"
                    f"  total={manager._t_cmd_end - manager._t_invocation:.1f}s"
                )
            status = "SUCCESS" if rc == 0 else "FAILED"
            print(divider(f"[{task_name}] completed"))
            print(f"status: {status}")
            print(f"exit: {rc}")
            print(f"log: {log_path}")
            if t:
                print(f"timing: {t}")
            donow_msg = check_donow(manager.session_id) if manager.session_id else None
            if donow_msg:
                print(f"\n{donow_msg}")
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
            manager.log_time(log_time)
            work.prepend_log_entry(manager.run_log_path, title, tag=f"[t:{task_name}]")
            try:
                if not skip_recent:
                    manager.append_context_recent(title, rc, ctx=ctx_injected)
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
            if rc == 3:
                print(
                    f"TASK_FAILED (rc={rc}) — rewrite input.md (get its path via "
                    f"`owrap get input`) before redispatching via orun."
                )
        return rc

    def _start_task_fallback(
        self, manager, input_path, content, log_time, skip_recent, model,
    ) -> int:
        fallback_file = FALLBACK_TASK
        ctx_cfg = _read_config()
        cp = context_path(manager.session_id)
        ctx_injected = False
        executor_md = get_agents_md_path()
        if work.should_inject_context(ctx_cfg, manager.session_id, cp):
            content = work.context_block(cp, executor_md) + content
            ctx_injected = True
        content += " " + ANTI_SUMMARY_SUFFIX
        fallback_file.write_text(f"--executor\n\n{content}")
        input_path.write_text("")

        cmd = ["opencode", "run", "--thinking"]
        if work.allow_all():
            cmd.append("--dangerously-skip-permissions")
        fb_model = get_dispatch_model(ctx_cfg, override=model, default_to_fast=False)
        if fb_model:
            cmd.extend(["-m", fb_model])
        cmd.extend(["--", shlex.quote(f"--executor --taskf {fallback_file}")])

        title = self._get_task_title(fallback_file)
        manager.t_cmd_start()
        Terminal(verbose=False).run(" ".join(cmd), print_output=True)
        manager.t_cmd_end()
        rc = 0
        manager.log_time(log_time)
        work.prepend_log_entry(manager.run_log_path, title, tag="[t:0]")
        try:
            if not skip_recent:
                manager.append_context_recent(title, rc, ctx=ctx_injected)
                manager.update_frequent_files()
        except Exception:
            pass
        return rc
