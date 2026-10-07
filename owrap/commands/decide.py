import os
import sys

from ..utils.memory.records import add_decision, resolve_memory_target
from ..utils.parser.text import preview
from ..utils.session.resolver import (
    session_file, _parse, resolve_session_or_exit,
)


class DecideRunner:
    """
    Add a timestamped decision entry to a project's main.md for the
    session's target project.
    """

    def run(self, target: str, text: str = None):
        """
        Resolve target to a project record, then prepend one timestamped
        decision bullet to its Decisions section.
        """
        if text is None:
            print('Usage: owrap decide <target> "<text>"')
            print()
            print("Examples:")
            print('  owrap decide myproject "Keep the dev/live split"')
            sys.exit(2)

        project_path = self._resolve_target(target)
        try:
            line = add_decision(project_path, text)
        except (OSError, ValueError) as exc:
            print(f"ERROR: {exc}")
            sys.exit(2)
        print(f'DECISION added to {project_path}: "{preview(text)}"')


    # Private Methods

    def _resolve_target(self, target):
        """
        Resolve a session id/project/repository name (or the currently
        attached session, if target is empty) to its project record file.
        """
        if target:
            sid = resolve_session_or_exit(target)
        else:
            sid = os.environ.get("SESSION_ID", "").strip()
            if not sid:
                print("ERROR: no target given and no session attached.")
                sys.exit(2)

        session = _parse(session_file(sid))
        if not session.get("target_kind"):
            print(f"ERROR: session {sid} has no project/repository target configured.")
            sys.exit(2)
        try:
            memory_target = resolve_memory_target(session)
        except (OSError, ValueError) as exc:
            print(f"ERROR: {exc}")
            sys.exit(2)
        if memory_target.kind == "repository":
            print("ERROR: repository-only sessions have no project decisions")
            sys.exit(2)
        return memory_target.project_path
