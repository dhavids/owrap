import json
import os

from . import Op
from ..record.identity import current_workspace
from ...ctx.dispatch import read_opencode_status_detail
from ...utils.parser.text import preview_lines
from ...utils.paths import (
    OWRAP_HOME, RUNTIME_LOG, _read_config, get_plan_path, get_self_path,
    get_workspace_config, session_agent_log_path, session_exec_output_path,
    session_input, session_msg_output_dir, session_task_output_dir,
)


class Self(Op):
    """
    Workspace/session facts that have no kind of their own to live on.
    """

    kind = "self"

    usage = {
        "get": {
            "usage": (
                "[home|opencode [reason]|config [workspace]|plan|input"
                "|output <kind>|runtime [history]|history] [--count <n>] "
                "[--tail <n>] [-g <pattern>] [--sid <id>]"
            ),
            "args": [
                ("home", "print the resolved OWRAP_HOME path"),
                ("opencode", "print the shared opencode health flag "
                             "(up/down); add 'reason' for why"),
                ("config", "print the attached session's effective config "
                           "(base merged with workspace); add 'workspace' "
                           "for just that workspace's own override file"),
                ("plan", "print the attached session's active plan"),
                ("input", "print the attached session's queued input"),
                ("output", "print the latest msg/task/agent/exec output "
                           "path + preview; a specific id is `owrap task "
                           "get <id>`/`owrap agent get <id>`/`owrap exec "
                           "get <id>`, not this"),
                ("runtime", "tail the raw rtlog, filtered by --sid/-g; "
                            "'runtime history' is an alias for 'history'"),
                ("history", "the session's last --count (default 5) "
                            "completed commands, paired with their argv"),
            ],
            "examples": [
                "", "home", "opencode", "opencode reason", "config",
                "config workspace", "plan", "output task", "runtime",
                "runtime -g server.spawn", "history", "history --count 10",
            ],
        },
    }

    messages = {"do": "{text}", "get": "{text}"}


    # Public Methods

    def do(self) -> None:
        """
        Print the staged self.md reference content.
        """
        self._ok("do", text=self._self_content())

    def get(
        self, what: str = None, detail: str = None, count: str = None,
        tail: str = None, grep: str = None, sid: str = None,
    ) -> None:
        """
        Report a workspace/session fact selected by `what` (see `usage`).
        """
        if what is None:
            self._ok("get", text=self._self_content())
        elif what == "home":
            self._ok("get", text=str(OWRAP_HOME))
        elif what == "opencode":
            self._ok("get", text=self._opencode_status(detail))
        elif what == "config":
            self._ok("get", text=self._config_dump(detail))
        elif what == "plan":
            self._ok("get", text=self._session_file_preview(get_plan_path, "plan"))
        elif what == "input":
            self._ok("get", text=self._session_file_preview(session_input, "input"))
        elif what == "output":
            self._ok("get", text=self._output_preview(detail))
        elif what == "runtime" and detail == "history":
            self._ok("get", text=self._runtime_history(count, sid))
        elif what == "runtime":
            self._ok("get", text=self._runtime_log(tail, grep, sid))
        elif what == "history":
            self._ok("get", text=self._runtime_history(detail or count, sid))
        else:
            self._usage("get")


    # Private Methods

    def _self_content(self) -> str:
        path = get_self_path()
        if not path.exists():
            self._fail("no staged self file; run `owrap sync`")
        return path.read_text().strip()

    def _opencode_status(self, detail: str = None) -> str:
        info = read_opencode_status_detail()
        if detail == "reason":
            return info["reason"] or "(none)"
        return info["status"]

    def _config_dump(self, detail: str = None) -> str:
        """
        Report the attached session's effective config (base
        defaults merged with its workspace's overrides), or --
        with `detail == "workspace"` -- just that workspace's own
        unmerged override file.
        """
        self._attached_sid()
        workspace = current_workspace()
        if detail == "workspace":
            config = get_workspace_config(workspace)
        else:
            config = _read_config(workspace)
        if not config:
            self._fail("no config found for the attached session's workspace")
        return json.dumps(config, indent=2, sort_keys=True)

    def _session_file_preview(self, path_fn, noun: str) -> str:
        sid = self._attached_sid()
        path = path_fn(sid)
        content = path.read_text() if path.exists() else f"(no {noun} yet)"
        return f"{path}\n\n{preview_lines(content)}"

    def _output_preview(self, kind: str) -> str:
        sid = self._attached_sid()
        if kind == "exec":
            path = session_exec_output_path(sid)
        elif kind == "agent":
            path = session_agent_log_path(sid)
        elif kind == "msg":
            path = self._latest_file(session_msg_output_dir(sid), "msg_*.log")
        elif kind == "task":
            path = self._latest_file(session_task_output_dir(sid), "*.log")
        else:
            self._usage("get")
        if path is None or not path.exists():
            return f"no {kind} output yet for session {sid}"
        return f"{path}\n\n{preview_lines(path.read_text())}"

    def _latest_file(self, directory, pattern: str):
        if not directory.is_dir():
            return None
        files = list(directory.glob(pattern))
        return max(files, key=lambda f: f.stat().st_mtime) if files else None

    def _runtime_log(self, tail: str, grep: str, sid: str) -> str:
        sid = sid or self._optional_sid()
        if not RUNTIME_LOG.exists():
            return f"log: {RUNTIME_LOG} (not found)\nno events"
        lines = [f"log: {RUNTIME_LOG} ({self._size_str(RUNTIME_LOG)})"]
        events = [
            event for event in self._parsed_events(RUNTIME_LOG, grep)
            if not sid or event.get("sid") == sid
        ]
        if not events:
            lines.append("no events")
            return "\n".join(lines)
        for event in events[-(int(tail) if tail else 50):]:
            lines.append(self._format_event(event))
        return "\n".join(lines)

    def _runtime_history(self, count: str, sid: str) -> str:
        sid = sid or self._optional_sid()
        if not RUNTIME_LOG.exists():
            return "No runtime log yet"
        starts, ends = {}, []
        for event in self._parsed_events(RUNTIME_LOG, None):
            if sid and event.get("sid") != sid:
                continue
            if event.get("ev") == "cmd.start":
                starts[event.get("pid")] = event
            elif event.get("ev") == "cmd.end":
                ends.append(event)
        if not ends:
            return f"No dispatch history for session {sid or '(none)'}"
        shown = ends[-(int(count) if count else 5):]
        lines = [f"history (last {len(shown)} of {len(ends)}):"]
        for event in shown:
            lines.append(self._format_history_line(event))
            start = starts.get(event.get("pid"))
            if start and start.get("argv"):
                lines.append(f"    argv: {start['argv']}")
            for key in ("error", "result"):
                if event.get(key):
                    lines.append(f"    {key}: {event[key]}")
        return "\n".join(lines)

    def _parsed_events(self, path, grep: str) -> list:
        events = []
        for line in path.read_text().splitlines():
            if grep and grep not in line:
                continue
            try:
                events.append(json.loads(line))
            except (json.JSONDecodeError, ValueError):
                continue
        return events

    def _format_event(self, event: dict) -> str:
        parts = [(event.get("ts") or "")[11:19], event.get("ev", "")]
        for key, value in event.items():
            if key not in ("ts", "pid", "sid", "ev"):
                parts.append(f"{key}={value}")
        return "  ".join(parts)

    def _format_history_line(self, event: dict) -> str:
        ts = (event.get("ts") or "")[11:19]
        cmd, rc = event.get("cmd", "?"), event.get("rc", "?")
        status = "done(ok)" if rc == 0 else f"done(rc={rc})"
        dur, sid = event.get("dur_s", 0), event.get("sid") or "?"
        return f"  {cmd:<16}  {status:<12}  {dur:.2f}s  @ {ts}  [{sid}]"

    def _optional_sid(self) -> str:
        return os.environ.get("SESSION_ID", "").strip()

    def _size_str(self, path) -> str:
        size = path.stat().st_size
        return f"{size / 1024:.1f}K" if size >= 1024 else f"{size}B"

    def _attached_sid(self) -> str:
        sid = os.environ.get("SESSION_ID", "").strip()
        if not sid:
            self._fail("no SESSION_ID — run this from an attached window")
        return sid
