import os
import sys
from pathlib import Path

from ..utils.paths import (
    RUNTIME_HOME, RUNTIME_LOG, get_plan_path, session_input, context_path,
    FALLBACK_PLAN, FALLBACK_TASK,
    FALLBACK_EXEC_OUTPUT, FALLBACK_TASK_OUTPUT,
    session_msg_output_dir, session_task_output_dir,
    session_agent_full_log_dir, session_agent_log_path,
)

_EXEC_OUTPUT_MAX_LINES = 15

class GetRunner:
    """
    Retrieve owrap session data, files, and configuration.
    """

    def run(self, what, session_id=None, dispatch_id=None):
        """
        Print the requested resource to stdout.
        """
        if what == "home":
            print(RUNTIME_HOME)
            return

        sid = self._resolve_session_id(session_id)
        if not sid:
            print("No active session")
            sys.exit(1)

        sf = RUNTIME_HOME / "sessions" / f"{sid}.session"
        sdata = self._parse_session_file(sf)

        if what == "session":
            self._print_session(sid, sdata, sf)
            return

        if what in ("area", "research"):
            val = sdata.get(what, "")
            if not val:
                print(f"No {what} configured for session {sid}")
                sys.exit(1)
            print(val)
            return

        if what == "config":
            workspace = sdata.get("workspace", "")
            if not workspace:
                print(f"No workspace configured for session {sid}")
                sys.exit(1)
            cfg_path = RUNTIME_HOME / "configs" / f"{workspace}.json"
            header = f"# config: {cfg_path}"
            print(header)
            if not cfg_path.exists():
                print(f"No config file found for workspace {workspace}")
                sys.exit(1)
            import json
            cfg = json.loads(cfg_path.read_text())
            print(json.dumps(cfg, indent=2))
            return

        if what == "agents":
            from ..utils.paths import session_agent_log_path
            fpath = session_agent_log_path(sid)
            header = f"# agents: {fpath}"
            print(header)
            if not fpath.exists():
                print(f"No agent output for session {sid}")
                sys.exit(1)
            content = fpath.read_text().strip()
            if not content:
                print("(empty)")
                return
            if dispatch_id:
                marker = f"[a:{dispatch_id}]"
                blocks = self._split_agent_blocks(content)
                matched = None
                for block in reversed(blocks):
                    if marker in block.splitlines()[0]:
                        matched = block
                        break
                if matched is None:
                    print(f"No agent output for id '{dispatch_id}'")
                    sys.exit(1)
                print(matched.rstrip())
            else:
                print(content)
            return

        if what in ("memory", "project"):
            research = sdata.get("research", "")
            if not research:
                print(f"No research configured for session {sid}")
                sys.exit(1)
            workspace = sdata.get("workspace", "")
            research_root = self._get_research_root(workspace)
            if what == "memory":
                fpath = Path(research_root) / "memory" / f"{research}.md"
            else:
                fpath = Path(research_root) / "projects" / f"{research}.md"
            if not fpath.exists():
                print(f"{what}/{research}.md does not exist (research: {research})")
                sys.exit(1)
            area = sdata.get("area", "")
            header = f"# {what}: {fpath}"
            content = self._extract_content(fpath, area)
            print(header)
            print(content)
            return

        fmap = {
            "plan": get_plan_path(sid),
            "input": session_input(sid),
            "context": context_path(sid),
        }
        if what not in fmap:
            print(f"Usage: owrap get <what> [--session <id>]")
            print("  plan     — current plan file")
            print("  input    — current input file")
            print("  context  — current context file")
            print("  session  — session fields table")
            print("  agents   — agents/output.log for this session")
            print("           (all subagent summaries)")
            print("  memory   — memory/<research>.md (requires research)")
            print("  project  — projects/<research>.md (requires research)")
            print("  area     — current area name")
            print("  research — current research name")
            print("  config   — full workspace config JSON")
            print("  home     — resolved OWRAP_HOME (no session required)")
            sys.exit(1)

        research = sdata.get("research", "")
        if what in ("plan", "input") and research == "owrap":
            fpath = FALLBACK_PLAN if what == "plan" else FALLBACK_TASK
            print(
                f"# {what}: {fpath}  "
                f"(research=owrap: dispatch via `owrap f {fpath}`)"
            )
            if not fpath.exists():
                label = "plan" if what == "plan" else "input"
                print(f"No {label} file for session {sid}")
            else:
                content = fpath.read_text().strip()
                print("Plan is empty" if what == "plan" and not content else content)
            if what == "input":
                session_fpath = fmap["input"]
                print(f"\n# input (session): {session_fpath}")
                if session_fpath.exists():
                    session_content = session_fpath.read_text().strip()
                else:
                    session_content = ""
                print("(empty)" if not session_content else session_content)
        else:
            fpath = fmap[what]
            header = f"# {what}: {fpath}"
            print(header)
            if not fpath.exists():
                label_map = {
                    "plan": "plan file",
                    "input": "input file",
                    "context": "context file",
                }
                label = label_map[what]
                print(f"No {label} for session {sid}")
                sys.exit(1)
            content = fpath.read_text().strip()
            if what == "plan" and not content:
                print("Plan is empty")
            else:
                print(content)

    def run_output(self, kind, dispatch_id=None, head=5, tail=5, session_id=None):
        """Resolve and display output for the given kind.

        Prints the resolved file path, then a head/tail preview of its
        contents.  If no matching output exists, prints a clear message
        and exits with code 1.
        """
        if kind is None:
            print(
                "Usage: owrap get output <msg|task|agent|exec> "
                "[--id <id>] [--head N] [--tail N] [--session <sid>]"
            )
            sys.exit(1)

        sid = self._resolve_session_id(session_id)

        if kind == "exec":
            fpath = FALLBACK_EXEC_OUTPUT
            if not fpath.exists():
                print(f"No exec output at {fpath}")
                sys.exit(1)
        elif kind == "task":
            if sid:
                fpath = self._resolve_task_output(sid, dispatch_id)
            else:
                fpath = FALLBACK_TASK_OUTPUT
                if not fpath.exists():
                    print(f"No task output at {fpath}")
                    sys.exit(1)
        elif kind == "msg":
            if not sid:
                print("No active session for msg output")
                sys.exit(1)
            fpath = self._resolve_msg_output(sid, dispatch_id)
        elif kind == "agent":
            if not sid:
                print("No active session for agent output")
                sys.exit(1)
            fpath = self._resolve_agent_output(sid, dispatch_id)
        else:
            print(f"Unknown output kind: {kind}")
            sys.exit(1)

        print(f"path: {fpath}")
        self._print_head_tail(fpath, head, tail)

    def run_runtime(self, tail=50, ev_prefix=None, sid=None):
        """
        Read and display the runtime log.
        """
        import json
        if not RUNTIME_LOG.exists():
            print(f"log: {RUNTIME_LOG} (not found)")
            print("no events")
            return
        size = RUNTIME_LOG.stat().st_size
        size_str = f"{size / 1024:.1f}K" if size >= 1024 else f"{size}B"
        print(f"log: {RUNTIME_LOG} ({size_str})")
        lines = RUNTIME_LOG.read_text().splitlines()
        events = []
        for line in lines:
            try:
                obj = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            if ev_prefix and not obj.get("ev", "").startswith(ev_prefix):
                continue
            if sid and obj.get("sid") != sid:
                continue
            events.append(obj)
        if not events:
            print("no events")
            return
        for ev in events[-tail:]:
            ts = ev.get("ts", "")
            if ts:
                ts = ts[11:19]  # HH:MM:SS
            ev_name = ev.get("ev", "")
            parts = [ts, ev_name]
            for k, v in ev.items():
                if k in ("ts", "pid", "sid", "ev"):
                    continue
                parts.append(f"{k}={v}")
            print("  ".join(parts))

    def _resolve_session_id(self, session_id):
        if session_id:
            return session_id
        sid = os.environ.get("SESSION_ID", "").strip()
        if sid:
            return sid
        ccsid = os.environ.get("CLAUDE_CODE_SESSION_ID", "").strip()
        if ccsid:
            ptr = RUNTIME_HOME / "sessions" / "by_ccsid" / ccsid
            if ptr.exists():
                return ptr.read_text().strip()
        return None

    def _parse_session_file(self, path):
        data = {}
        if path.exists():
            for line in path.read_text().splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    data[k.strip()] = v.strip()
        return data

    def _get_research_root(self, workspace):
        if workspace:
            cfg_path = RUNTIME_HOME / "configs" / f"{workspace}.json"
            if cfg_path.exists():
                import json
                cfg = json.loads(cfg_path.read_text())
                if "research_root" in cfg:
                    return cfg["research_root"]
        return f"{workspace}/docs/research" if workspace else ""

    def _print_session(self, sid, sdata, sf):
        if not sf.exists():
            print("No active session")
            return
        header = f"# session: {sf}"
        base_keys = [
            "session_id", "research", "area", "child",
            "workspace", "started", "last_refresh",
        ]
        header_len = max(len(k) for k in base_keys + list(sdata.keys()))
        rows = []
        for label in base_keys:
            val = sdata.get(label, "—")
            rows.append(f"  {label:<{header_len}}  {val}")
        print(header)
        for row in rows:
            print(row)

    def _extract_content(self, fpath, area):
        content = fpath.read_text()
        if not area:
            return content
        lines = content.splitlines(keepends=True)
        marker = f"## {area}"
        in_section = False
        result = []
        for line in lines:
            if line.strip() == marker:
                in_section = True
                result.append(line)
                continue
            if in_section:
                stripped = line.strip()
                if stripped.startswith("## ") and not stripped.startswith("### "):
                    break
                result.append(line)
        if not result:
            return content
        return "".join(result).rstrip()

    def _resolve_most_recent_file(self, directory, pattern="*.log"):
        """Return the most recently modified file matching *pattern* in
        *directory*, or None if the directory is empty or missing.
        """
        d = Path(directory)
        if not d.is_dir():
            return None
        files = list(d.glob(pattern))
        if not files:
            return None
        return max(files, key=lambda f: f.stat().st_mtime)

    def _resolve_msg_output(self, sid, dispatch_id):
        """Resolve the msg output file path for the given session and
        optional dispatch id.
        """
        msg_dir = session_msg_output_dir(sid)
        if dispatch_id:
            fpath = msg_dir / f"msg_{dispatch_id}.log"
            if not fpath.exists():
                print(f"No msg output for id '{dispatch_id}' at {fpath}")
                sys.exit(1)
            return fpath
        result = self._resolve_most_recent_file(msg_dir, "msg_*.log")
        if result is None:
            print(f"No msg output in {msg_dir}")
            sys.exit(1)
        return result

    def _resolve_task_output(self, sid, dispatch_id):
        """Resolve the task output file path for the given session and
        optional dispatch id.
        """
        task_dir = session_task_output_dir(sid)
        if dispatch_id:
            candidates = [
                task_dir / f"{dispatch_id}.log",
                task_dir / f"task_{dispatch_id}.log",
            ]
            for fpath in candidates:
                if fpath.exists():
                    return fpath
            print(
                f"No task output for id '{dispatch_id}' "
                f"(tried {[str(c) for c in candidates]})"
            )
            sys.exit(1)
        result = self._resolve_most_recent_file(task_dir, "*.log")
        if result is None:
            print(f"No task output in {task_dir}")
            sys.exit(1)
        return result

    def _resolve_agent_output(self, sid, dispatch_id):
        """Resolve the agent output file path for the given session and
        optional dispatch id.

        When *dispatch_id* is given, the summary log is scanned from the
        end (most recent first) for a line containing ``[a:<id>]``, and
        the ``**Log:** <path>`` reference is extracted.  If not found
        there, each agent log file is grepped directly for the marker.
        """
        agent_dir = session_agent_full_log_dir(sid)
        if dispatch_id:
            marker = f"[a:{dispatch_id}]"
            summary = session_agent_log_path(sid)
            if summary.exists():
                lines = summary.read_text().splitlines()
                for line in reversed(lines):
                    if marker in line:
                        log_ref = self._extract_log_path_from_line(line)
                        if log_ref and Path(log_ref).exists():
                            return Path(log_ref)
            if agent_dir.is_dir():
                files = sorted(
                    agent_dir.glob("*.log"),
                    key=lambda f: f.stat().st_mtime,
                    reverse=True,
                )
                for fpath in files:
                    content = fpath.read_text()
                    if marker in content:
                        return fpath
            print(f"No agent output for id '{dispatch_id}'")
            sys.exit(1)
        result = self._resolve_most_recent_file(agent_dir, "*.log")
        if result is None:
            print(f"No agent output in {agent_dir}")
            sys.exit(1)
        return result

    def _split_agent_blocks(self, content):
        """Split agent log content into blocks at ``## [a:...]`` headers."""
        import re
        pattern = re.compile(r'^## \[a:', re.MULTILINE)
        parts = pattern.split(content)
        # parts[0] is text before first header (usually empty); skip it
        blocks = []
        for part in parts[1:]:
            # Reconstruct the header prefix that split removed
            block = "## [a:" + part
            blocks.append(block)
        return blocks

    def _extract_log_path_from_line(self, line):
        """Extract the path after ``**Log:**`` from a summary line, or
        return None.
        """
        marker = "**Log:**"
        idx = line.find(marker)
        if idx == -1:
            return None
        return line[idx + len(marker):].strip()

    def _print_head_tail(self, fpath, head, tail):
        """Print the first *head* lines and last *tail* lines of *fpath*,
        with a total-line-count footer.

        For msg/task logs that contain section markers (INPUT, EXECUTOR
        OUTPUT, RESULT), skip the INPUT body and print the middle and
        result sections in full.
        """
        lines = fpath.read_text().splitlines()
        total = len(lines)
        if total == 0:
            print("(empty)")
            print(f"total: 0 lines")
            return
        head_lines = lines[:head]
        if total > head + tail:
            tail_lines = lines[-tail:]
        else:
            tail_lines = []

        # Detect section-marker format and handle specially
        section_indices = self._find_section_markers(lines)
        if section_indices is not None:
            self._print_sectioned(lines, total, section_indices)
            return

        for line in head_lines:
            print(line)
        if tail_lines:
            print(f"... ({total - head - len(tail_lines)} lines omitted)")
            for line in tail_lines:
                print(line)
        print(f"total: {total} lines")

    def _find_section_markers(self, lines):
        """Find INPUT, EXECUTOR OUTPUT, and RESULT section boundaries.

        Returns a dict with ``input_end``, ``exec_start``, ``exec_end``,
        ``result_start`` line indices, or None if markers are not found.
        """
        input_idx = None
        exec_idx = None
        result_idx = None
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("==========") and " INPUT " in stripped:
                input_idx = i
            elif stripped.startswith("==========") and " EXECUTOR OUTPUT " in stripped:
                exec_idx = i
            elif stripped.startswith("==========") and " RESULT " in stripped:
                result_idx = i
        if input_idx is not None and exec_idx is not None:
            return {
                "input_idx": input_idx,
                "exec_idx": exec_idx,
                "result_idx": result_idx,
            }
        return None

    def _print_sectioned(self, lines, total, section_indices):
        """Print sectioned msg/task log, skipping INPUT body."""
        input_idx = section_indices["input_idx"]
        exec_idx = section_indices["exec_idx"]
        result_idx = section_indices["result_idx"]

        # Print INPUT header + note it was skipped
        print(lines[input_idx])
        input_body_end = exec_idx
        input_body_lines = input_body_end - input_idx - 1
        if input_body_lines > 0:
            print(f"(INPUT section omitted — {input_body_lines} lines)")
        else:
            print("(INPUT section omitted)")

        # Print EXECUTOR OUTPUT section (capped to last N lines)
        if result_idx is not None:
            exec_end = result_idx
        else:
            exec_end = len(lines)
        exec_lines = exec_end - exec_idx
        if exec_lines > _EXEC_OUTPUT_MAX_LINES:
            omit_count = exec_lines - _EXEC_OUTPUT_MAX_LINES
            print(f"(EXECUTOR OUTPUT: {omit_count} lines omitted)")
            start = exec_end - _EXEC_OUTPUT_MAX_LINES
        else:
            start = exec_idx
        for i in range(start, exec_end):
            print(lines[i])

        # Print RESULT section in full
        if result_idx is not None:
            for i in range(result_idx, len(lines)):
                print(lines[i])

        print(f"total: {total} lines")
