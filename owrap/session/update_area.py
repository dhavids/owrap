import sys
from ..base import BaseRunner
from ..utils.session_resolver import resolve, update_session_field
from ..utils.paths import _read_config, context_path, get_plan_path, get_todo_path, session_input
from .orientation import print_orientation
from pathlib import Path


class UpdateAreaRunner(BaseRunner):
    def run(self, research=None, area=None):
        session_id, _, _ = resolve(mode="refresh")
        if research:
            update_session_field(session_id, "research", research)
        if area:
            update_session_field(session_id, "area", area)
        _rr = _read_config().get("research_root")
        memory_path = project_path = protocol_path = None
        if research and _rr:
            _mp = Path(_rr) / "memory" / f"{research}.md"
            _pp = Path(_rr) / "projects" / f"{research}.md"
            _prot = Path(_rr) / "update-protocol.md"
            memory_path = _mp if _mp.exists() else None
            project_path = _pp if _pp.exists() else None
            protocol_path = _prot if _prot.exists() else None
        cp = context_path(session_id)
        plan_path = get_plan_path(session_id)
        input_path = session_input(session_id)
        todo_path = get_todo_path(research)
        print_orientation(session_id, research, plan_path=plan_path, todo_path=todo_path,
                          input_path=input_path, context_path=cp,
                          area=area, memory_path=memory_path,
                          project_path=project_path, protocol_path=protocol_path)
        print(f"\n__OWRAP_EXPORT__ SESSION_ID={session_id}")
        if area:
            print(f"__OWRAP_EXPORT__ OWRAP_AREA={area}")
        sys.exit(0)
