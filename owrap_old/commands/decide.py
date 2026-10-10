import os
import sys

from owrap.utils.memory.records import (
    add_decision, clear_decisions, remove_decision, resolve_memory_target,
    touch_record_last_updated,
)
from owrap.utils.parser.text import preview
from owrap.utils.session.resolver import (
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

        memory_target = self._resolve_target(target)
        project_path = memory_target.project_path
        try:
            line = add_decision(project_path, text)
        except (OSError, ValueError) as exc:
            print(f"ERROR: {exc}")
            sys.exit(2)
        yaml_path = project_path.parent / f"{memory_target.project_id}.yaml"
        touch_record_last_updated(yaml_path)
        print(f'DECISION added to {project_path}: "{preview(text)}"')

    def run_remove(self, target: str, position: str):
        """
        Remove the decision at an arbitrary 1-indexed position outright;
        0 or -1 means first or last, same as `owrap todo remove`.
        """
        try:
            position_value = int(position)
        except (TypeError, ValueError):
            print(f"ERROR: position must be an integer, got '{position}'")
            sys.exit(2)
        if position_value < -1:
            print(f"ERROR: position must be 0, -1, or >= 1, got '{position_value}'")
            sys.exit(2)

        memory_target = self._resolve_target(target)
        project_path = memory_target.project_path
        try:
            removed = remove_decision(project_path, position_value)
        except (OSError, ValueError) as exc:
            print(f"ERROR: {exc}")
            sys.exit(2)
        yaml_path = project_path.parent / f"{memory_target.project_id}.yaml"
        touch_record_last_updated(yaml_path)
        print(f'DECISION removed from {project_path}: "{preview(removed)}"')

    def run_clear(self, target: str = None):
        """
        Remove every decision from the target's project.
        """
        memory_target = self._resolve_target(target)
        project_path = memory_target.project_path
        try:
            removed = clear_decisions(project_path)
        except (OSError, ValueError) as exc:
            print(f"ERROR: {exc}")
            sys.exit(2)
        yaml_path = project_path.parent / f"{memory_target.project_id}.yaml"
        touch_record_last_updated(yaml_path)
        print(f"DECISIONS cleared {removed} entry(ies) from {project_path}")


    # Private Methods

    def _resolve_target(self, target):
        """
        Resolve a session id/project/repository name (or the currently
        attached session, if target is empty) to its project MemoryTarget.
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
        return memory_target
