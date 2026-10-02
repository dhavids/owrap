import os
import re
import sys

from ..utils.paths import get_todo_file_path, todo_lock_path
from ..utils.filelock import file_lock
from ..utils.match import require_unique_match
from ..utils.parser.text import preview
from ..utils.session.session_resolver import (
    session_file, _parse, resolve_session_or_exit,
)

_ITEM_START_RE = re.compile(r"^\d+\.\s+\[([ xX])\]\s*(.*)$")


class TodoRunner:
    """
    Add, insert, or clear user-sourced todo entries for a research/area.
    """

    def run(self, target: str, arg2: str, arg3: str = None):
        """
        Resolve target to a research/area, then act based on position:
        no position appends to the end; 1, 2, 3... inserts before that
        1-indexed position, shifting the rest down; 0 or -1 updates the
        first or last item's text in place instead of inserting. New
        inserted items start unchecked; updated items keep their done state.
        """
        if arg2 is None:
            print('Usage: owrap todo <target> "<text>"')
            print('       owrap todo <target> <position> "<text>"')
            print("       owrap todo clear [<target>]")
            print()
            print("Examples:")
            print('  owrap todo myresearch "Fix the auth redirect bug"')
            print('  owrap todo myresearch 1 "Do this before the current top item"')
            print('  owrap todo myresearch 0 "Replace the first item\'s text"')
            print('  owrap todo myresearch -1 "Replace the last item\'s text"')
            print("  owrap todo clear myresearch")
            sys.exit(2)

        research, area = self._resolve_research_area(target)

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

        fpath = get_todo_file_path(research)
        lock = todo_lock_path(research)
        fpath.parent.mkdir(parents=True, exist_ok=True)

        with file_lock(lock):
            sections, order, preamble = self._read_sections(fpath)
            items = sections.get(area, [])
            updated = False
            if position is None:
                items.append((False, text))
            elif position in (0, -1):
                if not items:
                    print(f"ERROR: no item at position {position} to update.")
                    sys.exit(2)
                slot = 0 if position == 0 else -1
                items[slot] = (items[slot][0], text)
                updated = True
            else:
                idx = max(0, min(position - 1, len(items)))
                items.insert(idx, (False, text))
            sections[area] = items
            if area not in order:
                order.append(area)
            self._write_sections(fpath, sections, order, preamble)

        verb = "updated" if updated else "added to"
        print(f'TODO {verb} {research}/{area}: "{preview(text)}"')

    def run_clear(self, target: str = None):
        """
        Remove every checked (done) item from the target's area and
        renumber what remains.
        """
        research, area = self._resolve_research_area(target)
        fpath = get_todo_file_path(research)
        lock = todo_lock_path(research)

        with file_lock(lock):
            sections, order, preamble = self._read_sections(fpath)
            items = sections.get(area, [])
            remaining = [entry for entry in items if not entry[0]]
            removed = len(items) - len(remaining)
            sections[area] = remaining
            self._write_sections(fpath, sections, order, preamble)

        print(f"TODO cleared {removed} done item(s) from {research}/{area}")

    def run_done(self, target: str, selector: str):
        """
        Mark one pending item done, selected by 1-indexed position, the
        literal 'next' (first pending item in order), or a text snippet
        matched against pending item text.
        """
        if not selector:
            print('Usage: owrap todo done <target> <position|next|"<phrase>">')
            print()
            print("Examples:")
            print("  owrap todo done myresearch next")
            print("  owrap todo done myresearch 2")
            print('  owrap todo done myresearch "auth redirect bug"')
            sys.exit(2)

        research, area = self._resolve_research_area(target)
        fpath = get_todo_file_path(research)
        lock = todo_lock_path(research)

        with file_lock(lock):
            sections, order, preamble = self._read_sections(fpath)
            items = sections.get(area, [])
            idx = self._resolve_item_index(items, selector)
            _, text = items[idx]
            items[idx] = (True, text)
            sections[area] = items
            self._write_sections(fpath, sections, order, preamble)

        text_preview = preview(text.splitlines()[0])
        print(f'TODO marked done in {research}/{area}: "{text_preview}"')


    # Private Methods

    def _resolve_research_area(self, target):
        """
        Resolve a session id/research/area target (or the currently
        attached session, if target is empty) to a (research, area) pair.
        """
        if target:
            sid = resolve_session_or_exit(target)
        else:
            sid = os.environ.get("SESSION_ID", "").strip()
            if not sid:
                print("ERROR: no target given and no session attached.")
                sys.exit(2)

        session = _parse(session_file(sid))
        research = session.get("research", "")
        area = session.get("area", "")
        if not research or not area:
            print(f"ERROR: session {sid} has no research/area set.")
            sys.exit(2)
        return research, area

    def _resolve_item_index(self, items, selector):
        """
        Resolve a done-selector against items ([(done, text), ...]) to a
        single index: 'next' is the first pending item in order, a digit
        is a 1-indexed position, anything else is a case-insensitive
        substring matched against pending item text only. Exits with an
        error on no match or more than one match — never guesses.
        """
        if selector == "next":
            for i, (done, _) in enumerate(items):
                if not done:
                    return i
            print("ERROR: no pending items to mark done.")
            sys.exit(2)

        if selector.isdigit():
            position = int(selector)
            if position < 1 or position > len(items):
                print(f"ERROR: position {position} out of range (1-{len(items)}).")
                sys.exit(2)
            return position - 1

        needle = selector.lower()
        matches = [
            i for i, (done, text) in enumerate(items)
            if not done and needle in text.lower()
        ]
        return require_unique_match(
            matches, "pending item", selector,
            formatter=lambda i: f"{i + 1}. {items[i][1].splitlines()[0]}",
        )

    def _read_sections(self, fpath):
        """
        Parse todo/<research>.md into an ordered {area: [(done, text), ...]}
        dict, plus any preamble text above the first `## area` heading. An
        item starts at a `N. [ ]`/`N. [x]` line — the checkbox is the
        boundary, not the line itself, so everything up to the next
        checkbox line (or the next `## area` heading) belongs to that same
        item, however many lines it spans.
        """
        sections = {}
        order = []
        preamble_lines = []
        if not fpath.exists():
            return sections, order, ""
        current = None
        pending = None
        for line in fpath.read_text().splitlines():
            stripped = line.strip()
            if stripped.startswith("## "):
                self._flush_item(sections, current, pending)
                pending = None
                current = stripped[3:].strip()
                sections[current] = []
                order.append(current)
                continue
            if current is None:
                preamble_lines.append(line)
                continue
            m = _ITEM_START_RE.match(stripped)
            if m:
                self._flush_item(sections, current, pending)
                done = m.group(1).lower() == "x"
                pending = [done, [m.group(2)] if m.group(2) else []]
            elif pending is not None:
                pending[1].append(line)
        self._flush_item(sections, current, pending)
        preamble = "\n".join(preamble_lines).strip()
        return sections, order, preamble

    def _flush_item(self, sections, current, pending):
        """
        Append a completed (done, text) item to `sections[current]`, if one
        is pending. `text` joins the item's lines with embedded newlines
        for multi-line items.
        """
        if current is None or pending is None:
            return
        done, lines = pending
        sections[current].append((done, "\n".join(lines).rstrip()))

    def _write_sections(self, fpath, sections, order, preamble=""):
        """
        Serialize {area: [(done, text), ...]} back to todo/<research>.md,
        one `## <area>` block per section in `order`, with `preamble`
        restored above the first heading. Multi-line item text is written
        with its embedded newlines preserved verbatim.
        """
        blocks = []
        if preamble:
            blocks.append(preamble)
        for area in order:
            items = sections.get(area, [])
            numbered = "\n".join(
                f"{i}. [{'x' if done else ' '}] {text}"
                for i, (done, text) in enumerate(items, start=1)
            )
            block = f"## {area}\n\n{numbered}" if numbered else f"## {area}"
            blocks.append(block)
        fpath.write_text("\n\n".join(blocks) + "\n")
