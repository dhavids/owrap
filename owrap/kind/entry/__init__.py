from ...actions.access import Access
from ...actions.modify import Modify
from ...utils.io.yaml import touch_last_updated
from ...utils.parser.text import preview


class Entry(Modify, Access):
    """
    Base for every line-item-entry-shaped kind (todo, decision) -- a
    kind with no identity of its own, living as a bullet entry inside
    a parent record's markdown section. `Entry` isn't an action type
    itself; it's this base that binds `Modify` (already carrying
    `add`/`update`/`remove`/`clear`/`done`/`restore`/`set`) with
    `Access` (`get`), plus the contracts common to every entry kind
    specifically: `read` (so every entry kind can be read the same
    way) and the generic `_add`/`_update`/`_remove`/`_clear`/`_done`
    below, which a concrete kind feeds via its own raw item callback
    (`_add_item`, `_update_item`, `_remove_item`, `_clear_items`,
    `_done_item`) unless its own shape genuinely differs (`Decision`'s
    `add` has no position argument, so it overrides `_add` directly
    instead of using this one). A concrete kind sets its own `noun`
    (e.g. "goals"), which `Actions._resolve_target` picks up
    automatically.
    """


    # Private Methods

    def _default_get(self) -> None:
        """
        Fallback for `get` called with no args at all: report this
        kind's own record path rather than every item. A concrete
        kind overrides this if its own default should be something
        else.
        """
        self._path()

    def _touch(self, memory_target) -> None:
        """
        Bump the target project record's last_updated after an edit.
        """
        yaml_path = (
            memory_target.project_path.parent
            / f"{memory_target.project_id}.yaml"
        )
        touch_last_updated(yaml_path)

    def _edit(self, func, *args, **kwargs):
        """
        Call `func`, converting an OSError/ValueError into a clean
        failure exit instead of a raw traceback -- every verb below
        persists its edit through this.
        """
        try:
            return func(*args, **kwargs)
        except (OSError, ValueError) as exc:
            self._fail(exc)

    def _position(self, value) -> int:
        """
        Parse a 1-indexed position argument, accepting 0/-1 as
        aliases for the first/last item.
        """
        try:
            position = int(value)
        except (TypeError, ValueError):
            self._fail(f"position must be an integer, got '{value}'")
        if position < -1:
            self._fail(f"position must be 0, -1, or >= 1, got '{position}'")
        return position

    def _add(self, path, arg2: str, arg3: str = None) -> dict:
        """
        Act based on position: no position appends to the end; 1, 2,
        3... inserts before that 1-indexed position, shifting the rest
        down; 0 or -1 updates the first or last item's text in place
        instead of inserting. A kind whose add has no position concept
        (e.g. `Decision`) overrides this directly instead.
        """
        if arg2 is None:
            self._usage("add")

        if arg3 is not None:
            position = self._position(arg2)
            text = arg3
        else:
            position = None
            text = arg2

        self._edit(self._add_item, path, text, position)
        return {"text": preview(text)}

    def _update(self, path, position: str, text: str = None) -> dict:
        """
        Replace the item at an arbitrary 1-indexed position in place;
        0 or -1 means first or last.
        """
        if text is None:
            self._usage("update")
        position_value = self._position(position)

        self._edit(self._update_item, path, position_value, text)
        return {"text": preview(text)}

    def _remove(self, path, position: str) -> dict:
        """
        Remove the item at an arbitrary 1-indexed position outright;
        0 or -1 means first or last.
        """
        position_value = self._position(position)

        removed = self._edit(self._remove_item, path, position_value)
        return {"text": preview(removed)}

    def _clear(self, path) -> dict:
        """
        Remove every item the kind's `_clear_items` selects (e.g.
        every done goal, or every decision outright).
        """
        removed = self._edit(self._clear_items, path)
        return {"count": removed}

    def _done(self, path, selector: str = None) -> dict:
        """
        Mark one pending item done, selected by 1-indexed position,
        the literal 'next', or a text snippet match.
        """
        if not selector:
            self._usage("done")

        done = self._edit(self._done_item, path, selector)
        return {"text": preview(done)}

    def _add_item(self, path, text, position=None):
        raise ValueError(f"{self.kind} does not support add")

    def _update_item(self, path, position, text):
        raise ValueError(f"{self.kind} does not support update")

    def _remove_item(self, path, position):
        raise ValueError(f"{self.kind} does not support remove")

    def _clear_items(self, path):
        raise ValueError(f"{self.kind} does not support clear")

    def _done_item(self, path, selector):
        raise ValueError(f"{self.kind} does not support done")


    # Class Methods

    @classmethod
    def read(cls, path):
        """
        Return this kind's structured data read from `path`. A
        entry kind defines this to get `get` for free.
        """
        raise ValueError(f"{cls.kind} does not support read")
