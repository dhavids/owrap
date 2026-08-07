import json
import os
import re
import shlex
import shutil
import signal
import sys
import time
from datetime import datetime

from ..utils.terminal import Terminal
from ..utils.output_parser import OutputParser
from ..base import BaseRunner
from ..constants import (
    AGENT_KILL_S, NO_OUTPUT_AGENT_S, AGENT_INLINE_MAX_CHARS, AGENT_TIMEOUT_DEFAULT,
    LOG_WRAP_WIDTH, AGENT_GRACE_MIN_S, AGENT_GRACE_MAX_S, AGENT_GRACE_LOW_ANCHOR_S,
    AGENT_GRACE_HIGH_ANCHOR_S,
)
from ..utils.pool import _pool_active, pick_server, update_last_used
from ..utils.paths import (
    _read_config, get_dispatch_model, get_workspace_path, format_failure_pointer,
    session_agents_dir, session_agent_log_path, session_agent_full_log_dir, RUNNING_DIR,
)
from ..utils.snippet import wrap_log_text, divider


_AGENT_SUMMARY_HEADER_RE = re.compile(r'^\+?#{1,6}\s*Summary\s*$', re.MULTILINE)


def _count_running_agent_jobs(session_id: str) -> int:
    """Count still-running agent-kind sentinel files for the given session."""
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
        if data.get("session_id") != session_id:
            continue
        if data.get("kind") != "agent":
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


def _compute_agent_grace(timeout_s):
    lo_t, hi_t = AGENT_GRACE_LOW_ANCHOR_S, AGENT_GRACE_HIGH_ANCHOR_S
    lo_g, hi_g = AGENT_GRACE_MIN_S, AGENT_GRACE_MAX_S
    if timeout_s <= lo_t:
        return lo_g
    if timeout_s >= hi_t:
        return hi_g
    frac = (timeout_s - lo_t) / (hi_t - lo_t)
    return lo_g + frac * (hi_g - lo_g)


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


class AgentsRunner(BaseRunner):
    """Runner for dispatching and managing sub-agent tasks."""

    def __init__(
        self, manager, logger=None, allow_all=False, model=None, disablewd=False,
    ):
        super().__init__(manager, logger, allow_all)
        self.model = model
        self.disablewd = disablewd

    def run(self, action):
        if action == "clear":
            self._clear_agent_output()
        sys.exit(0)

    def run_agent(
        self, data, agent_id=None, log_time=False, timeout=None,
        model_override=None, clear=False,
    ):
        """Dispatch a sub-agent task and wait for completion."""
        self._cleanup_recently_done()
        if clear:
            self._clear_agent_output()
        if _pool_active():
            try:
                url = pick_server("agent")
            except Exception:
                print(format_failure_pointer("NO_SERVER", self.manager.session_id))
                sys.exit(1)
        else:
            url = self.manager.ensure_running()
        return self._run_agent(
            data, url, log_time, agent_id=agent_id, timeout=timeout,
            disablewd=self.disablewd,
        )

    def _clear_agent_output(self):
        sid = self.manager.session_id
        if not sid:
            print("Error: no active session", file=sys.stderr)
            sys.exit(1)
        running = _count_running_agent_jobs(sid)
        if running > 0:
            print(
                f"[owrap] skipping --clear: {running} agent job(s) "
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

    def _write_agent_log(self, agent_id, data, full_log_path, summary):
        import fcntl
        log_path = session_agent_log_path(self.manager.session_id)
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

    def _run_agent(
        self, data, url, log_time, agent_id=None, timeout=None, disablewd=False,
    ):
        self._install_sigterm_handler()

        if agent_id:
            print(f"[a:{agent_id}]", flush=True)
        _sentinel_id = agent_id or f"fg_{int(time.time())}"
        _timestamp_id = f"{int(time.time() * 1000)}"
        _agent_output_path = (
            session_agent_full_log_dir(self.manager.session_id)
            / f"{_timestamp_id}.log"
        )
        sentinel = self._write_sentinel(
            _sentinel_id, data[:60], kind="agent", call_type="agent", url=url, 
            output_path=_agent_output_path)
        _ctx_cfg = _read_config()
        AGENT_TIMEOUT = timeout if timeout is not None else AGENT_TIMEOUT_DEFAULT
        AGENT_GRACE = _compute_agent_grace(AGENT_TIMEOUT)
        AGENT_KILL_TIMEOUT = AGENT_TIMEOUT + AGENT_GRACE
        dispatch_data = data + _AGENT_INSTRUCTIONS_SUFFIX.format(timeout=AGENT_TIMEOUT)
        input_file = None
        if len(dispatch_data) > AGENT_INLINE_MAX_CHARS:
            input_file = (
                session_agent_full_log_dir(self.manager.session_id)
                / f"{_timestamp_id}_input.md"
            )
            input_file.parent.mkdir(parents=True, exist_ok=True)
            input_file.write_text(dispatch_data)
            exec_prompt = f"--executor --taskf {input_file}"
        else:
            exec_prompt = f"--executor {dispatch_data}"
        cmd = ["opencode", "run", "--thinking", "--dir", str(get_workspace_path())]
        if self.allow_all:
            cmd.append("--dangerously-skip-permissions")
        model = get_dispatch_model(_ctx_cfg, override=self.model, default_to_fast=True)
        if model:
            cmd.extend(["-m", model])
        if url:
            cmd.extend(["--attach", url])
        cmd.extend(["--", shlex.quote(exec_prompt)])

        if self.logger:
            self.logger.debug("run agent cmd=%s", " ".join(cmd))
        rc = 1
        timed_out = False
        infra_failure = False
        result = {}
        session_agent_full_log_dir(self.manager.session_id).mkdir(
            parents=True, exist_ok=True)
        agent_log = (
            session_agent_full_log_dir(self.manager.session_id)
            / f"{_timestamp_id}.log"
        )
        print(f"log: {agent_log}", flush=True)
        watchdog = None
        try:
            self.manager.t_cmd_start()
            with open(agent_log, "w") as tee:
                _header = (
                    f"[{datetime.now().isoformat()}] AGENT START\n\n"
                    f"{divider('INPUT')}\n\n"
                    f"{wrap_log_text(dispatch_data, LOG_WRAP_WIDTH)}\n\n"
                )
                tee.write(_header)
                tee.flush()
                tee.write(f"{divider('EXECUTOR OUTPUT')}\n")
                tee.write(f"[server: {url or 'direct'}]\n\n")
                tee.flush()
                terminal = Terminal(verbose=False)
                from ..utils.watchdog import Watchdog
                def _agent_stop():
                    setattr(self, '_stall_killed', True)
                    terminal.terminate_process()
                if not disablewd:
                    watchdog = Watchdog(
                        log_path=agent_log,
                        kind="agent",
                        sentinel_path=sentinel,
                        url=url,
                        kill_callback=_agent_stop,
                        kill_after_s=float(
                            _read_config().get("agent_kill_s", AGENT_KILL_S)),
                        no_output_s=float(
                            _read_config().get(
                                "no_output_agent_s", NO_OUTPUT_AGENT_S,
                            ),
                        ),
                        unresponsive_callback=_agent_stop,
                    )
                    watchdog.start()
                else:
                    watchdog = None
                result = terminal.run(
                    " ".join(cmd), print_output=True, capture_output=True,
                    timeout=AGENT_KILL_TIMEOUT, tee_file=tee, use_pty=True,
                    cwd=str(get_workspace_path()),
                )

            self.manager.t_cmd_end()
        except Exception as exc:
            self.manager.t_cmd_end()
            if self.logger:
                self.logger.error("run agent error: %s", exc)
        finally:
            if watchdog:
                watchdog.stop()
            rc = self._finish_dispatch(
                "orun agent", result, watchdog, sentinel, agent_log,
                self.manager.session_id, AGENT_KILL_TIMEOUT,
                AGENT_TIMEOUT_DEFAULT,
            )
            timed_out = bool(result.get("timed_out"))
            infra_failure = rc == 1
            if input_file is not None:
                input_file.unlink(missing_ok=True)
            summary = _extract_agent_summary(result.get("stdout") or "")
            self._write_agent_log(agent_id, data, _agent_output_path, summary)
            if self.logger:
                _timeout_tag = " (timeout)" if timed_out else ""
                self.logger.info(
                    "run agent done data=%.80r rc=%d%s",
                    data, rc, _timeout_tag,
                )
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
