import argparse
import os
import sys
import time
from pathlib import Path

from ..base import BaseRunner
from .start import StartRunner
from ..utils.paths import SESSION_DIR, get_plan_path, get_todo_path, session_input, _read_config, context_path, get_workspace_config, BASE_CONFIG_FILE
from ..utils.session_resolver import resolve, update_session_field, list_sessions, _parse, SESSIONS_DIR
from .orientation import print_orientation


class RefreshRunner(BaseRunner):
    def run(self, shell_pid=None, session_file=None, research=None, session_id=None, area=None):
        if session_id is not None:
            session_path = Path.home() / ".owrap" / "sessions" / f"{session_id}.session"
            if not session_path.exists():
                print(f"ERROR: session '{session_id}' not found. Use 'owrap stat' to list sessions.")
                sys.exit(2)
        else:
            session_id, session_path, source = resolve(mode="refresh")
            if session_id is None:
                print("ERROR: cannot refresh — no SESSION_ID in env and no Claude session anchor matched.")
                print()
                print("Known sessions:")
                for s in list_sessions():
                    ccsid_val = s.get("claude_session_id", "-")
                    print(f"  {s['session_id']}  research={s.get('research','-')}  started={s.get('started','-')}  ccsid={ccsid_val[:8] if ccsid_val != '-' else '-'}")
                print()
                print("Either: export SESSION_ID=<id>  OR  ~/bin/owrap attach <id>  OR  ~/bin/owrap start <name>")
                sys.exit(2)

        data = _parse(session_path)
        existing_research = data.get("research")
        existing_area = data.get("area")
        workspace_name = data.get("workspace") or _read_config().get("default_workspace", "")
        if research is None:
            research = existing_research
        if research is None:
            research = _read_config().get("default_research")

        from ..utils.pool import _pool_active, ensure_min_servers, _ensure_keepalive
        if _pool_active():
            ensure_min_servers()
            _ensure_keepalive()
        else:
            url = self.manager.ensure_running()
            if url is None:
                os.environ["SESSION_ID"] = session_id
                StartRunner(self.manager).run(shell_pid=shell_pid, research=research)
                return

        if research != existing_research:
            update_session_field(session_id, "research", research)
        if area is not None:
            update_session_field(session_id, "area", area)
        area_val = area if area is not None else existing_area

        self.manager._housekeeping()

        plan_path = get_plan_path(session_id)
        todo_path = get_todo_path(research)
        input_path = session_input(session_id)

        if self.logger:
            self.logger.info("refresh session=%s research=%s", session_id, research or "none")
        cp = context_path(session_id)
        memory_path = project_path = protocol_path = None
        if research:
            _rr = _read_config().get("research_root")
            if _rr:
                _mp = Path(_rr) / "memory" / f"{research}.md"
                _pp = Path(_rr) / "projects" / f"{research}.md"
                _prot = Path(_rr) / "update-protocol.md"
                memory_path = _mp if _mp.exists() else None
                project_path = _pp if _pp.exists() else None
                protocol_path = _prot if _prot.exists() else None
        print_orientation(session_id, research, plan_path=plan_path, todo_path=todo_path, input_path=input_path, context_path=cp,
                          area=area_val, memory_path=memory_path, project_path=project_path, protocol_path=protocol_path)
        update_session_field(session_id, "last_refresh", time.strftime("%Y-%m-%dT%H:%M:%S"))
        print(f"\n__OWRAP_EXPORT__ SESSION_ID={session_id}")
        if area_val:
            print(f"__OWRAP_EXPORT__ OWRAP_AREA={area_val}")
        sys.exit(0)


def main():
    parser = argparse.ArgumentParser(description="Refresh an owrap session")
    parser.add_argument("research", nargs="?", default=None, help="Research project name")
    parser.add_argument("--shell-pid", type=int, default=None, help="Shell PID")
    parser.add_argument("--session-file", type=str, default=None, help="Session file path")
    args = parser.parse_args()

    from ..manager import Manager
    manager = Manager()
    RefreshRunner(manager).run(shell_pid=args.shell_pid, session_file=args.session_file, research=args.research)


if __name__ == "__main__":
    main()
