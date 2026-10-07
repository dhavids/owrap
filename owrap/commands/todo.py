import os
import sys

from ..utils.memory.goals import edit_goals
from ..utils.memory.records import resolve_memory_target
from ..utils.parser.text import preview
from ..utils.session.resolver import (
    session_file, _parse, resolve_session_or_exit,
)


class TodoRunner:
    """
    Add, insert, update, or clear goal items in a project's main.md (or
    clear done items / mark one done) for the session's target project.
    """

    def run(self, target: str, arg2: str, arg3: str = None):
        """
        Resolve target to a project goal file, then act based on position:
        no position appends to the end; 1, 2, 3... inserts before that
        1-indexed position, shifting the rest down; 0 or -1 updates the
        first or last item's text in place instead of inserting. New
        inserted items start unchecked; updated items keep their done state.
        """
        if arg2 is None:
            print('Usage: owrap todo <target> "<text>"')
            print('       owrap todo <target> <position> "<text>"')
            print('       owrap todo update <target> <position> "<text>"')
            print("       owrap todo clear [<target>]")
            print()
            print("Examples:")
            print('  owrap todo myproject "Fix the auth redirect bug"')
            print('  owrap todo myproject 1 "Do this before the current top item"')
            print('  owrap todo myproject 0 "Replace the first item\'s text"')
            print('  owrap todo myproject -1 "Replace the last item\'s text"')
            print('  owrap todo update myproject 3 "Replace item 3 in place"')
            print("  owrap todo clear myproject")
            sys.exit(2)

        goal_path = self._resolve_target(target)

        if arg3 is not None:
            try:
                position = int(arg2)
            except ValueError:
                print(f"ERROR: position must be an integer, got '{arg2}'")
                sys.exit(2)
            if position < -1:
                print(f"ERROR: position must be 0, -1, or >= 1, got '{position}'")
                sys.exit(2)
            text = arg3
        else:
            position = None
            text = arg2

        try:
            edit_goals(goal_path, "add", text, position)
        except (OSError, ValueError) as exc:
            print(f"ERROR: {exc}")
            sys.exit(2)
        print(f'GOAL added to {goal_path}: "{preview(text)}"')

    def run_update(self, target: str, position: str, text: str):
        """
        Replace the goal at an arbitrary 1-indexed position in place,
        keeping its done state; 0 or -1 means first or last, same as
        `run`'s in-place form.
        """
        if text is None:
            print('Usage: owrap todo update <target> <position> "<text>"')
            sys.exit(2)
        try:
            position_value = int(position)
        except (TypeError, ValueError):
            print(f"ERROR: position must be an integer, got '{position}'")
            sys.exit(2)
        if position_value < -1:
            print(f"ERROR: position must be 0, -1, or >= 1, got '{position_value}'")
            sys.exit(2)

        goal_path = self._resolve_target(target)
        try:
            edit_goals(goal_path, "update", text, position_value)
        except (OSError, ValueError) as exc:
            print(f"ERROR: {exc}")
            sys.exit(2)
        print(f'GOAL updated in {goal_path}: "{preview(text)}"')

    def run_clear(self, target: str = None):
        """
        Remove every checked (done) goal item from the target's project.
        """
        goal_path = self._resolve_target(target)
        try:
            removed, _ = edit_goals(goal_path, "clear")
        except (OSError, ValueError) as exc:
            print(f"ERROR: {exc}")
            sys.exit(2)
        print(f"GOALS cleared {removed} done item(s) from {goal_path}")

    def run_done(self, target: str, selector: str):
        """
        Mark one pending goal item done, selected by 1-indexed position,
        the literal 'next' (first pending item in order), or a text
        snippet matched against pending item text.
        """
        if not selector:
            print('Usage: owrap todo done <target> <position|next|"<phrase>">')
            print()
            print("Examples:")
            print("  owrap todo done myproject next")
            print("  owrap todo done myproject 2")
            print('  owrap todo done myproject "auth redirect bug"')
            sys.exit(2)

        goal_path = self._resolve_target(target)
        try:
            _, selected = edit_goals(goal_path, "done", selector)
        except (OSError, ValueError) as exc:
            print(f"ERROR: {exc}")
            sys.exit(2)
        print(f'GOAL marked done in {goal_path}: "{preview(selected)}"')


    # Private Methods

    def _resolve_target(self, target):
        """
        Resolve a session id/project/repository name (or the currently
        attached session, if target is empty) to its project goal file.
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
            print("ERROR: repository-only sessions have no project goals")
            sys.exit(2)
        return memory_target.project_path
