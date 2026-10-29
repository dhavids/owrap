import fcntl
import json
import os
import re
import shlex
import shutil
import sys
import time
from datetime import datetime

from . import Dispatch
from ...dispatch import work
from ...dispatch.manager import Manager
from ...utils.constants import (
    AGENT_GRACE_HIGH_ANCHOR_S, AGENT_GRACE_LOW_ANCHOR_S, AGENT_GRACE_MAX_S,
    AGENT_GRACE_MIN_S, AGENT_INLINE_MAX_CHARS, AGENT_KILL_S, AGENT_TIMEOUT_DEFAULT,
    INFRA_FAILURE_AGENT_S, LOG_WRAP_WIDTH, NO_OUTPUT_AGENT_S,
)
from ...utils.dispatch.pool import (
    _pool_active, pick_server, record_responsive, release_server,
    update_last_used,
)
from ...utils.dispatch.terminal import Terminal
from ...utils.dispatch.watchdog import Watchdog
from ...utils.parser.output import OutputParser
from ...utils.parser.snippet import divider, wrap_log_text
from ...utils.paths import (
    RUNNING_DIR, _read_config, format_failure_pointer, get_dispatch_model,
    get_workspace_path, session_agent_full_log_dir, session_agent_log_path,
)

_AGENT_SUMMARY_HEADER_RE = re.compile(r'^\+?#{1,6}\s*Summary\s*$', re.MULTILINE)

_AGENT_INSTRUCTIONS_SUFFIX = (
    "\n\n---\n"
    "Aim to finish this task within {timeout} seconds — you have a short grace "
    "period after that to finish writing your summary before being killed. "
    "Respond directly in your own final message — do not write your findings "
    "into any file via Edit or Write, even if asked to compare/audit something. "
    "End your response with exactly the heading '## Summary' (not '## Findings', "
    "'## Verdict', or any other wording) containing your findings — this is "
    "what gets read back afterward."
)


def _count_running_agent_jobs(session_id: str) -> int:
    """
    Count still-running agent-kind sentinel files for the given session.
    """
    if not RUNNING_DIR.exists():
        return 0
    count = 0
    for f in RUNNING_DIR.iterdir():
        if f.suffix != ".json":
            continue
        try:
            data = json.loads(f.read_text())
        except Exception:
            continue
        if data.get("session_id") != session_id or data.get("kind") != "agent":
            continue
        pid = data.get("pid")
        if pid:
            try:
                os.kill(pid, 0)
                count += 1
            except OSError:
                pass
    return count


def _extract_agent_summary(output_text: str) -> str:
    text = output_text or ""
    m = _AGENT_SUMMARY_HEADER_RE.search(text)
    if not m:
        headers = list(re.finditer(r'^\+?##\s+\S.*$', text, re.MULTILINE))
        if headers:
            last = headers[-1]
            body = OutputParser.ANSI_RE.sub('', text[last.end():]).strip()
            title = last.group().strip().lstrip('+').strip()
            return f"[no '## Summary' header — last section '{title}'] {body}"
        tail = OutputParser.ANSI_RE.sub('', text).strip()[-500:]
        return f"[no '## Summary' header found — raw tail] {tail}"
    return OutputParser.ANSI_RE.sub('', text[m.end():]).strip()


def _compute_agent_grace(timeout_s: float) -> float:
    lo_t, hi_t = AGENT_GRACE_LOW_ANCHOR_S, AGENT_GRACE_HIGH_ANCHOR_S
    lo_g, hi_g = AGENT_GRACE_MIN_S, AGENT_GRACE_MAX_S
    if timeout_s <= lo_t:
        return lo_g
    if timeout_s >= hi_t:
        return hi_g
    frac = (timeout_s - lo_t) / (hi_t - lo_t)
    return lo_g + frac * (hi_g - lo_g)


class Agent(Dispatch):
    """
    Dispatch a sub-agent task and wait for its summary (the `oagent`
    command). The timeout carries a grace period for the agent to write
    its summary, and completion extracts the `## Summary` section; the
    full log stays on disk. `clear` wipes this session's agent output.
    """

    kind = "agent"

    usage = {
        "start": {
            "usage": "<data> [--id <id>] [--timeout <s>] [--clear]",
            "args": [
                ("data", "the sub-agent's task description"),
                ("id", "this agent dispatch's own id, for parallel tracking"),
                ("clear", "wipe this session's prior agent output first"),
            ],
            "examples": ["'review owrap/cli.py for dead code'"],
        },
        "get": {
            "usage": "<task_id>",
            "args": [("task_id", "an agent task's id (the id passed to start)")],
            "examples": ["a_1234"],
        },
        "clear": {
            "usage": "",
            "args": [],
            "examples": [""],
        },
    }


    # Public Methods

    def start(
        self, data: str, id: str = None, log_time: bool = False,
        timeout: float = None, model: str = None, clear: bool = False,
        disablewd: bool = False,
    ) -> None:
        """
        Dispatch `data` as a sub-agent task and block until it
        finishes (or times out past its grace period), then append
        its `## Summary` section to this session's agent log.
        """
        if data is None or data == "-":
            data = sys.stdin.read()
        manager = Manager()
        work.cleanup_recently_done()
        if clear:
            self._clear(manager)

        if _pool_active():
            try:
                url = pick_server("agent")
            except Exception:
                print(format_failure_pointer("NO_SERVER", manager.session_id))
                sys.exit(1)
        else:
            url = manager.ensure_running()

        if id:
            print(f"[a:{id}]", flush=True)
        sentinel_id = id or f"fg_{int(time.time())}"
        timestamp_id = f"{int(time.time() * 1000)}"
        agent_log = session_agent_full_log_dir(manager.session_id) / f"{timestamp_id}.log"
        sentinel = work.write_sentinel(
            manager.session_id, sentinel_id, data[:60], kind="agent",
            call_type="agent", url=url, output_path=agent_log,
        )
        ctx_cfg = _read_config()
        agent_timeout = timeout if timeout is not None else AGENT_TIMEOUT_DEFAULT
        agent_grace = _compute_agent_grace(agent_timeout)
        agent_kill_timeout = agent_timeout + agent_grace
        dispatch_data = data + _AGENT_INSTRUCTIONS_SUFFIX.format(timeout=agent_timeout)

        input_file = None
        if len(dispatch_data) > AGENT_INLINE_MAX_CHARS:
            input_file = (
                session_agent_full_log_dir(manager.session_id)
                / f"{timestamp_id}_input.md"
            )
            input_file.parent.mkdir(parents=True, exist_ok=True)
            input_file.write_text(dispatch_data)
            exec_prompt = f"--executor --taskf {input_file}"
        else:
            exec_prompt = f"--executor {dispatch_data}"

        cmd = ["opencode", "run", "--thinking", "--dir", str(get_workspace_path())]
        if work.allow_all():
            cmd.append("--dangerously-skip-permissions")
        dispatch_model = get_dispatch_model(ctx_cfg, override=model, default_to_fast=True)
        if dispatch_model:
            cmd.extend(["-m", dispatch_model])
        if url:
            cmd.extend(["--attach", url])
        cmd.extend(["--", shlex.quote(exec_prompt)])

        state = work.new_signal_state()
        work.install_sigterm_handler(state)
        result = {}
        session_agent_full_log_dir(manager.session_id).mkdir(parents=True, exist_ok=True)
        print(f"log: {agent_log}", flush=True)
        watchdog = None
        try:
            manager.t_cmd_start()
            with open(agent_log, "w") as tee:
                tee.write(
                    f"[{datetime.now().isoformat()}] AGENT START\n\n"
                    f"{divider('INPUT')}\n\n"
                    f"{wrap_log_text(dispatch_data, LOG_WRAP_WIDTH)}\n\n"
                )
                tee.flush()
                tee.write(f"{divider('EXECUTOR OUTPUT')}\n")
                tee.write(f"[server: {url or 'direct'}]\n\n")
                tee.flush()
                terminal = Terminal(verbose=False)

                def _agent_stop():
                    state["stall_killed"] = True
                    terminal.terminate_process()
                if not disablewd:
                    watchdog = Watchdog(
                        log_path=agent_log, kind="agent", sentinel_path=sentinel,
                        url=url, kill_callback=_agent_stop,
                        kill_after_s=float(ctx_cfg.get("agent_kill_s", AGENT_KILL_S)),
                        no_output_s=float(
                            ctx_cfg.get("no_output_agent_s", NO_OUTPUT_AGENT_S),
                        ),
                        infra_failure_s=float(
                            ctx_cfg.get(
                                "infra_failure_agent_s", INFRA_FAILURE_AGENT_S,
                            ),
                        ),
                        unresponsive_callback=_agent_stop,
                    )
                    watchdog.start()
                result = terminal.run(
                    " ".join(cmd), print_output=True, capture_output=True,
                    timeout=agent_kill_timeout, tee_file=tee, use_pty=True,
                    cwd=str(get_workspace_path()),
                )
            manager.t_cmd_end()
        except Exception:
            manager.t_cmd_end()
        finally:
            if watchdog:
                watchdog.stop()
            rc = work.finish_dispatch(
                "orun agent", result, watchdog, sentinel, agent_log,
                agent_kill_timeout, AGENT_TIMEOUT_DEFAULT, state=state,
            )
            if input_file is not None:
                input_file.unlink(missing_ok=True)
            summary = _extract_agent_summary(result.get("stdout") or "")
            self._write_agent_log(manager, id, data, agent_log, summary)
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

    def clear(self) -> None:
        """
        Wipe this session's agent output log/full-log directory --
        refuses if any agent job is still running for it.
        """
        self._clear(Manager())


    # Private Methods

    def _default_get(self) -> None:
        """
        Print this session's accumulated agent-output digest.
        """
        sid = Manager().session_id
        if not sid:
            self._fail("no active session")
        log_path = session_agent_log_path(sid)
        print(f"# agents: {log_path}")
        if not log_path.exists():
            self._fail(f"no agent output for session {sid}")
        content = log_path.read_text().strip()
        print(content or "(empty)")

    def _clear(self, manager) -> None:
        sid = manager.session_id
        if not sid:
            self._fail("no active session")
        running = _count_running_agent_jobs(sid)
        if running > 0:
            print(
                f"[owrap] skipping clear: {running} agent job(s) "
                f"still running for this session"
            )
            return
        log_path = session_agent_log_path(sid)
        full_log_dir = session_agent_full_log_dir(sid)
        if log_path.exists():
            log_path.unlink()
        if full_log_dir.exists():
            shutil.rmtree(full_log_dir)
        print(f"[owrap] cleared agent output for session {sid}")

    def _write_agent_log(self, manager, agent_id, data, full_log_path, summary) -> None:
        log_path = session_agent_log_path(manager.session_id)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        snippet = " ".join(data.split())[:150]
        entry = (
            f"## [a:{agent_id or 'noid'}] {datetime.now().isoformat()}\n\n"
            f"**Input:** {snippet}\n\n"
            f"**Log:** {full_log_path}\n\n"
            f"**Summary:**\n\n{summary}\n\n"
        )
        log_path.touch(exist_ok=True)
        with open(log_path, "a") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            f.write(entry)
            f.flush()
            fcntl.flock(f, fcntl.LOCK_UN)
