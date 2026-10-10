class Clear:
    """
    Default `clear`: resolve the target, hand the actual edit off to
    the kind's `_clear` callback for its payload, touch the record,
    then run the kind's optional `_on_clear` hook (a no-op unless a
    kind needs extra side effects beyond the edit itself) -- if that
    hook returns an error message, fail with it instead of reporting
    success. A kind that hasn't defined `_clear` refuses immediately,
    without attempting to resolve a target at all; one whose clear
    doesn't fit this shape overrides `clear` directly instead of
    defining `_clear`.
    """

    def clear(self, target=None):
        """
        Resolve the target and delegate the edit to `_clear`.
        """
        if type(self)._clear is Clear._clear:
            raise ValueError(f"{self.kind} does not support clear")
        memory_target = self._resolve_target(target)
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
