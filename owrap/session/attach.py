import sys

from ..base import BaseRunner
from ..utils.session_resolver import attach, list_sessions, _parse
from ..utils.paths import get_plan_path, get_todo_path, session_input, context_path
from .orientation import print_orientation


class AttachRunner(BaseRunner):
    def run(self, target_session_id=None):
        if not target_session_id:
            print("ERROR: owrap attach <session_id> — missing session_id.")
            print()
            print("Known sessions:")
            for s in list_sessions():
                ccsid_val = s.get("claude_session_id", "-")
                print(f"  {s['session_id']}  research={s.get('research','-')}  started={s.get('started','-')}  ccsid={ccsid_val[:8] if ccsid_val != '-' else '-'}")
            sys.exit(2)
        try:
            sid, sf, prev = attach(target_session_id)
        except (FileNotFoundError, RuntimeError) as e:
            print(f"ERROR: {e}")
            sys.exit(2)

        data = _parse(sf)
        research = data.get("research", "")
        url = data.get("server_url", "")

        plan_path = get_plan_path(sid)
        todo_path = get_todo_path(research)
        input_path = session_input(sid)
        cp = context_path(sid)

        self.manager.session_id = sid
        print(f"ATTACHED session={sid}  research={research or '-'}  prev_session_for_this_window={prev or '-'}")
        print_orientation(sid, research, url, plan_path, todo_path, input_path, context_path=cp)
        print(f"\n__OWRAP_EXPORT__ SESSION_ID={sid}")
        sys.exit(0)
