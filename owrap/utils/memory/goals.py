import os
import re
import tempfile
from pathlib import Path

from ..filelock import file_lock

_GOAL_RE = re.compile(r"^(?:- |\d+\. )\[([ xX])\] (.*)$")
_GOALS_HEADING = re.compile(r"(?m)^## Goals\s*$")
_NEXT_HEADING = re.compile(r"(?m)^## ")


def _section(content: str) -> tuple[str, str, str]:
    match = _GOALS_HEADING.search(content)
    if not match:
        raise ValueError("project file has no ## Goals section")
    next_heading = _NEXT_HEADING.search(content, match.end())
    end = next_heading.start() if next_heading else len(content)
    return content[:match.end()], content[match.end():end], content[end:]


def _items(body: str) -> list[tuple[bool, str]]:
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


def read_goals(path: Path) -> list[tuple[bool, str]]:
    """
    Return the goals from a project or subproject Markdown file.
    """
    _, body, _ = _section(path.read_text())
    return _items(body)


def edit_goals(
    path: Path, action: str, text: str = "", position: int | None = None,
) -> tuple[int, str]:
    """
    Edit the Goals section and return the number changed and selected text.
    """
    with file_lock(path.with_suffix(path.suffix + ".lock")):
        before, body, after = _section(path.read_text())
        preamble = []
        for line in body.splitlines():
            if _GOAL_RE.match(line):
                break
            preamble.append(line)
        items = _items(body)
        selected = text
        if action == "add":
            if position in (0, -1):
                if not items:
                    raise ValueError("no goal at that position")
                index = 0 if position == 0 else len(items) - 1
                items[index] = (items[index][0], text)
            else:
                index = len(items) if position is None else max(0, position - 1)
                items.insert(min(index, len(items)), (False, text))
            changed = 1
        elif action == "done":
            if text == "next":
                matches = [
                    i for i, (done, _) in enumerate(items) if not done
                ][:1]
            elif text.isdigit():
                matches = [int(text) - 1]
            else:
                matches = [
                    i for i, (done, goal) in enumerate(items)
                    if not done and text.lower() in goal.lower()
                ]
            if len(matches) != 1 or not 0 <= matches[0] < len(items):
                raise ValueError("goal selector must match one goal")
            index = matches[0]
            selected = items[index][1]
            items[index] = (True, selected)
            changed = 1
        elif action == "update":
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
            items[index] = (items[index][0], text)
            changed = 1
        elif action == "remove":
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
            selected = items[index][1]
            del items[index]
            changed = 1
        elif action == "clear":
            remaining = [item for item in items if not item[0]]
            changed = len(items) - len(remaining)
            items = remaining
        else:
            raise ValueError(f"unknown goal action: {action}")
        lines = [
            f"- [{'x' if done else ' '}] {goal}"
            for done, goal in items
        ]
        intro = "\n".join(preamble).strip()
        goal_body = "\n\n".join(part for part in (intro, "\n".join(lines)) if part)
        # before/after's own whitespace is regex-dependent, so rebuild it fresh.
        tail_sep = "\n\n\n" if after else "\n"
        content = before.rstrip() + "\n\n" + goal_body.rstrip() + tail_sep + after
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
        try:
            with os.fdopen(fd, "w") as handle:
                handle.write(content)
            os.chmod(tmp, path.stat().st_mode)
            os.replace(tmp, path)
        finally:
            Path(tmp).unlink(missing_ok=True)
    return changed, selected
