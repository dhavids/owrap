class Clear:
    """
    Default `clear`: resolve the target, run the kind's `_clear`
    callback for the edit, touch the record, then run the optional
    `_on_clear` hook, failing with its message if it returns one. A kind
    without `_clear` refuses before resolving a target.
    """

    def clear(self, target=None):
        """
        Resolve the target and delegate the edit to `_clear`.
        """
        if type(self)._clear is Clear._clear:
            raise ValueError(f"{self.kind} does not support clear")
        memory_target = self._resolve_target(target, write=True)
        fields = self._clear(memory_target.project_path)
        self._touch(memory_target)
        error = self._on_clear(memory_target, fields)
        if error:
            self._fail(error)
        self._ok("clear", path=memory_target.project_path, **fields)

    def _clear(self, path):
        raise ValueError(f"{self.kind} does not support clear")

    def _on_clear(self, memory_target, fields):
        return None
