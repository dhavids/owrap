import os
import sys
from pathlib import Path

from ..utils.paths import RUNTIME_HOME, get_plan_path, session_input, context_path, FALLBACK_PLAN, FALLBACK_TASK


class GetRunner:
    def run(self, what, session_id=None):
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
            print("(empty)" if not content else content)
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
            print("  agents   — agents/output.log for this session (all subagent summaries)")
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
            print(f"# {what}: {fpath}  (research=owrap: dispatch via `owrap f {fpath}`)")
            if not fpath.exists():
                print(f"No {'plan' if what == 'plan' else 'input'} file for session {sid}")
            else:
                content = fpath.read_text().strip()
                print("Plan is empty" if what == "plan" and not content else content)
            if what == "input":
                session_fpath = fmap["input"]
                print(f"\n# input (session): {session_fpath}")
                session_content = session_fpath.read_text().strip() if session_fpath.exists() else ""
                print("(empty)" if not session_content else session_content)
        else:
            fpath = fmap[what]
            header = f"# {what}: {fpath}"
            print(header)
            if not fpath.exists():
                label = {"plan": "plan file", "input": "input file", "context": "context file"}[what]
                print(f"No {label} for session {sid}")
                sys.exit(1)
            content = fpath.read_text().strip()
            if what == "plan" and not content:
                print("Plan is empty")
            else:
                print(content)

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
        header_len = max(len(k) for k in ["session_id", "research", "area", "child", "workspace", "started", "last_refresh"] + list(sdata.keys()))
        rows = []
        for label in ["session_id", "research", "area", "child", "workspace", "started", "last_refresh"]:
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
