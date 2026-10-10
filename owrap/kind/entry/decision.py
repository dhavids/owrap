import time
from pathlib import Path

from . import Entry
from ...utils.constants import (
    DECISION_ESCALATE_THRESHOLD, DECISION_NOTICE_THRESHOLD,
    DECISION_PRUNE_TARGET_MAX, DECISION_PRUNE_TARGET_MIN,
)
from ...utils.io.filelock import file_lock
from ...utils.io.atomic import write_atomic
from ...utils.parser.sections import extract_section, replace_section
from ...utils.parser.text import preview


class Decision(Entry):
    """
    A timestamped decision line-item under a project/subproject's
    `## Decisions` section. Fully self-contained -- owns its own
    decisions-section editing rather than calling into
    utils.memory.records.
    """

    kind = "decision"
    noun = "decisions"

    usage = {
        "add": {
            "usage": '<target> "<text>"',
            "args": [
                ("target", "session id, or project/repository name"),
                ("text", "the decision text"),
            ],
            "examples": ['myproject "Keep the dev/live split"'],
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
        "get": {
            "usage": "[<target> [<position|all>]]",
            "args": [
                ("target", "session id, or project/repository name; "
                           "omitted entirely reports the record's path"),
                ("position", "1-indexed position, 0/-1 for first/last, or "
                             "'all'/omitted for every decision"),
            ],
            "examples": ["myproject 1", "myproject all", "(no args)"],
            "purpose": "List decisions for a project/repository/session target",
            "group": "record",
        },
    }

    messages = {
        "add": 'DECISION added to {path}: "{text}"',
        "remove": 'DECISION removed from {path}: "{text}"',
        "clear": "DECISIONS cleared {count} entry(ies) from {path}",
        "get": "{text}",
        "path": "{path}",
    }


    # Private Methods

    def _default_get(self) -> None:
        """
        Report this project's Decisions count, escalating from a
        notice to a prune demand past the configured thresholds --
        `get`'s whole meaning for a bare call, instead of reporting
        the record's path like the base `Entry._default_get` does.
        """
        path = self._resolve_target(None).project_path
        count = len(self.read(path))
        text = f"decisions: {count} ({path})"
        if count >= DECISION_ESCALATE_THRESHOLD:
            text += (
                f"\nPRUNE NOW ({DECISION_ESCALATE_THRESHOLD}+) -- prune "
                f"down to {DECISION_PRUNE_TARGET_MIN}-{DECISION_PRUNE_TARGET_MAX}"
            )
        elif count >= DECISION_NOTICE_THRESHOLD:
            text += (
                f"\nconsider pruning ({DECISION_NOTICE_THRESHOLD}+) -- "
                f"prune down to {DECISION_PRUNE_TARGET_MIN}-"
                f"{DECISION_PRUNE_TARGET_MAX}"
            )
        self._ok("get", text=text)

    def _format_item(self, item) -> str:
        """
        Render one decision line, previewed if long.
        """
        return preview(item)

    def _add(self, path, text: str = None, arg3: str = None) -> dict:
        """
        Prepend one timestamped decision bullet to the project --
        overrides the base `_add` since decisions have no position
        argument, unlike a goal's insert-before-position shape.
        """
        if text is None:
            self._usage("add")

        self._edit(self._add_item, path, text)
        return {"text": preview(text)}

    def _add_item(self, path: Path, text: str) -> str:
        """
        Prepend one timestamped bullet to the Decisions section,
        returning the full bullet line written.
        """
        with file_lock(path.with_suffix(path.suffix + ".lock")):
            content = path.read_text()
            line = f"- {time.strftime('%Y-%m-%d %H:%M')} — {text}"
            lines = Decision._lines(content)
            new_block = "\n".join(["## Decisions", "", line] + lines)
            content = replace_section(content, "## Decisions", new_block)
            write_atomic(path, content)
        return line

    def _remove_item(self, path: Path, position: int) -> str:
        """
        Remove the decision at an arbitrary 1-indexed position (0 or
        -1 for first/last), returning the removed line's text.
        """
        with file_lock(path.with_suffix(path.suffix + ".lock")):
            content = path.read_text()
            lines = Decision._lines(content)
            if not lines:
                raise ValueError("no decision at that position")
            if position == 0:
                index = 0
            elif position == -1:
                index = len(lines) - 1
            else:
                index = position - 1
            if not 0 <= index < len(lines):
                raise ValueError("position out of range")
            removed = lines.pop(index)
            new_block = "\n".join(["## Decisions", ""] + lines)
            content = replace_section(content, "## Decisions", new_block)
            write_atomic(path, content)
        return removed.removeprefix("- ").strip()

    def _clear_items(self, path: Path) -> int:
        """
        Remove every decision from the Decisions section, returning
        the number removed.
        """
        with file_lock(path.with_suffix(path.suffix + ".lock")):
            content = path.read_text()
            lines = Decision._lines(content)
            content = replace_section(content, "## Decisions", "## Decisions\n")
            write_atomic(path, content)
        return len(lines)


    # Class Methods

    @classmethod
    def read(cls, path: Path) -> list:
        """
        Return every decision line (full bullet text, stripped) from
        a project or subproject Markdown file.
        """
        lines = cls._lines(path.read_text())
        return [line.removeprefix("- ").strip() for line in lines]


    # Static Methods

    @staticmethod
    def _lines(content: str) -> list:
        """
        Return the Decisions section's non-blank bullet lines, raw.
        """
        existing = extract_section(content, "## Decisions")
        return [
            line for line in (existing.splitlines()[1:] if existing else [])
            if line.strip()
        ]
