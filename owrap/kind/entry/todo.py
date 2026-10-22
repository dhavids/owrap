import re
from pathlib import Path

from . import Entry
from ...utils.io.filelock import file_lock
from ...utils.io.atomic import write_atomic
from ...utils.parser.text import preview

_GOAL_RE = re.compile(r"^(?:- |\d+\. )\[([ xX])\] (.*)$")
_GOALS_HEADING = re.compile(r"(?m)^## Goals\s*$")
_NEXT_HEADING = re.compile(r"(?m)^## ")


class Todo(Entry):
    """
    A goal line-item under a project/subproject's `## Goals` section.
    Fully self-contained -- owns its own goals-section parsing/editing
    rather than calling into utils.memory.goals.
    """

    kind = "todo"
    noun = "goals"

    usage = {
        "add": {
            "usage": '<target> [<position>] "<text>"',
            "args": [
                ("target", "session id, or project/repository name"),
                ("position", "optional; 1-indexed insert position, or "
                             "0/-1 to replace the first/last item in place"),
                ("text", "the goal text"),
            ],
            "examples": [
                'myproject "Fix the auth redirect bug"',
                'myproject 1 "Do this before the current top item"',
                'myproject 0 "Replace the first item\'s text"',
                'myproject -1 "Replace the last item\'s text"',
            ],
            "purpose": "Add a goal to a project/repository/session target",
            "group": "record",
        },
        "update": {
            "usage": '<target> <position> "<text>"',
            "args": [
                ("target", "session id, or project/repository name"),
                ("position", "1-indexed position to replace; 0/-1 for first/last"),
                ("text", "the replacement goal text"),
            ],
            "examples": ['myproject 2 "Replace item 2 in place"'],
        },
        "remove": {
            "usage": "<target> <position>",
            "args": [
                ("target", "session id, or project/repository name"),
                ("position", "1-indexed position to delete; 0/-1 for first/last"),
            ],
            "examples": ["myproject 2"],
        },
        "clear": {
            "usage": "[<target>]",
            "args": [
                ("target", "session id, or project/repository name; defaults "
                           "to the attached session"),
            ],
            "examples": ["myproject"],
        },
        "done": {
            "usage": '<target> <position|next|"<phrase>">',
            "args": [
                ("target", "session id, or project/repository name"),
                ("selector", "1-indexed position, 'next' for the first "
                             "pending item, or a text snippet to match"),
            ],
            "examples": [
                "myproject next",
                "myproject 2",
                'myproject "auth redirect bug"',
            ],
        },
        "get": {
            "usage": '[<target> [<position|all>]]',
            "args": [
                ("target", "session id, or project/repository name; "
                           "omitted entirely reports the record's path"),
                ("position", "1-indexed position, 0/-1 for first/last, or "
                             "'all'/omitted for every goal"),
            ],
            "examples": ["myproject 1", "myproject all", "(no args)"],
            "purpose": "List goals for a project/repository/session target",
            "group": "record",
        },
    }

    messages = {
        "add": 'GOAL added to {path}: "{text}"',
        "update": 'GOAL updated in {path}: "{text}"',
        "remove": 'GOAL removed from {path}: "{text}"',
        "clear": "GOALS cleared {count} done item(s) from {path}",
        "done": 'GOAL marked done in {path}: "{text}"',
        "get": "{text}",
        "path": "{path}",
    }


    # Private Methods

    def _format_item(self, item) -> str:
        """
        Render one (done, text) goal item as a checkbox line,
        previewed if long.
        """
        done, text = item
        return f"[{'x' if done else ' '}] {preview(text)}"

    def _add_item(self, path: Path, text: str, position: int = None) -> None:
        """
        Insert a goal before the 1-indexed position (appending if
        omitted), or replace the first/last item's text in place for
        position 0/-1. New inserted items start unchecked; updated
        items keep their done state.
        """
        with file_lock(path.with_suffix(path.suffix + ".lock")):
            preamble, items = Todo._read_items(path)
            if position in (0, -1):
                if not items:
                    raise ValueError("no goal at that position")
                index = 0 if position == 0 else len(items) - 1
                items[index] = (items[index][0], text)
            else:
                index = len(items) if position is None else max(0, position - 1)
                items.insert(min(index, len(items)), (False, text))
            Todo._write_items(path, preamble, items)

    def _update_item(self, path: Path, position: int, text: str) -> None:
        """
        Replace the goal at a 1-indexed position, keeping its done
        state; 0 or -1 means first or last.
        """
        with file_lock(path.with_suffix(path.suffix + ".lock")):
            preamble, items = Todo._read_items(path)
            index = Todo._index(items, position)
            items[index] = (items[index][0], text)
            Todo._write_items(path, preamble, items)

    def _remove_item(self, path: Path, position: int) -> str:
        """
        Delete the goal at a 1-indexed position outright, returning
        its text; 0 or -1 means first or last.
        """
        with file_lock(path.with_suffix(path.suffix + ".lock")):
            preamble, items = Todo._read_items(path)
            index = Todo._index(items, position)
            removed = items.pop(index)[1]
            Todo._write_items(path, preamble, items)
        return removed

    def _clear_items(self, path: Path) -> int:
        """
        Remove every checked goal, returning the number removed.
        """
        with file_lock(path.with_suffix(path.suffix + ".lock")):
            preamble, items = Todo._read_items(path)
            remaining = [item for item in items if not item[0]]
            removed = len(items) - len(remaining)
            Todo._write_items(path, preamble, remaining)
        return removed

    def _done_item(self, path: Path, selector: str) -> str:
        """
        Mark one pending goal done by position, 'next', or a text
        snippet match, returning its text.
        """
        with file_lock(path.with_suffix(path.suffix + ".lock")):
            preamble, items = Todo._read_items(path)
            if selector == "next":
                matches = [i for i, (done, _) in enumerate(items) if not done][:1]
            elif selector.isdigit():
                matches = [int(selector) - 1]
            else:
                matches = [
                    i for i, (done, goal) in enumerate(items)
                    if not done and selector.lower() in goal.lower()
                ]
            if len(matches) != 1 or not 0 <= matches[0] < len(items):
                raise ValueError("goal selector must match one goal")
            index = matches[0]
            done_text = items[index][1]
            items[index] = (True, done_text)
            Todo._write_items(path, preamble, items)
        return done_text


    # Class Methods

    @classmethod
    def read(cls, path: Path) -> list:
        """
        Return the goals from a project or subproject Markdown file.
        """
        _, body, _ = cls._section(path.read_text())
        return cls._items(body)


    # Static Methods

    @staticmethod
    def _section(content: str) -> tuple:
        match = _GOALS_HEADING.search(content)
        if not match:
            raise ValueError("project file has no ## Goals section")
        next_heading = _NEXT_HEADING.search(content, match.end())
        end = next_heading.start() if next_heading else len(content)
        return content[:match.end()], content[match.end():end], content[end:]

    @staticmethod
    def _items(body: str) -> list:
        items = []
        pending = None
        for line in body.splitlines():
            match = _GOAL_RE.match(line)
            if match:
                if pending is not None:
                    items.append((pending[0], "\n".join(pending[1]).strip()))
                pending = [match.group(1).lower() == "x", [match.group(2)]]
            elif pending is not None:
                pending[1].append(line)
        if pending is not None:
            items.append((pending[0], "\n".join(pending[1]).strip()))
        return items

    @staticmethod
    def _index(items: list, position: int) -> int:
        if not items:
            raise ValueError("no goal at that position")
        if position == 0:
            index = 0
        elif position == -1:
            index = len(items) - 1
        else:
            index = position - 1
        if not 0 <= index < len(items):
            raise ValueError("position out of range")
        return index

    @staticmethod
    def _read_items(path: Path) -> tuple:
        """
        Return the Goals section's intro text and its (done, text)
        items.
        """
        _, body, _ = Todo._section(path.read_text())
        preamble = []
        for line in body.splitlines():
            if _GOAL_RE.match(line):
                break
            preamble.append(line)
        return "\n".join(preamble).strip(), Todo._items(body)

    @staticmethod
    def _write_items(path: Path, preamble: str, items: list) -> None:
        """
        Rebuild the Goals section from its intro text and items and
        write the file back out.
        """
        before, _, after = Todo._section(path.read_text())
        lines = [f"- [{'x' if done else ' '}] {goal}" for done, goal in items]
        goal_body = "\n\n".join(part for part in (preamble, "\n".join(lines)) if part)
        # before/after's own whitespace is regex-dependent, so rebuild it fresh.
        tail_sep = "\n\n\n" if after else "\n"
        content = before.rstrip() + "\n\n" + goal_body.rstrip() + tail_sep + after
        write_atomic(path, content)
