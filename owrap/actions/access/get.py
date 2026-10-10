from ...utils.parser.text import preview


class Get:
    """
    Default `get`: resolve the target, read its items via the kind's
    `read` accessor, and print one item (1-indexed position, 0/-1
    for first/last) or all of them when position is omitted or
    "all" -- the kind-action equivalent of the old `get <kind>`
    command. Other code that needs a kind's data internally (not a
    printed message) calls `_get` directly instead of `read` itself.
    """

    def get(self, target, position: str = None) -> None:
        """
        Resolve the target and print one item or all of them.
        """
        result = self._get(target, position)
        if isinstance(result, list):
            text = "\n".join(self._format_item(item) for item in result)
            self._ok("get", text=text or "(none)")
        else:
            self._ok("get", text=self._format_item(result))

    def _get(self, target, position: str = None):
        """
        Resolve the target and return the raw item, or the full list
        when position is omitted or "all" -- the internal accessor
        other code calls to get the value itself, not a message.
        """
        if not hasattr(self, "read"):
            raise ValueError(f"{self.kind} does not support get")
        memory_target = self._resolve_target(target)
        items = self.read(memory_target.project_path)
        if position is None or position == "all":
            return items
        if not items:
            self._fail("no item at that position")
        position_value = self._position(position)
        if position_value == 0:
            index = 0
        elif position_value == -1:
            index = len(items) - 1
        else:
            index = position_value - 1
        if not 0 <= index < len(items):
            self._fail("position out of range")
        return items[index]

    def _format_item(self, item) -> str:
        """
        Render one item returned by `read` as display text, previewed
        (head and tail) if long. Override for anything richer than
        the item's own string form.
        """
        return preview(str(item))
