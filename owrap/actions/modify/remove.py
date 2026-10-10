class Remove:
    """
    Default `remove`: resolve the target, hand the actual edit off
    to the kind's `_remove` callback for its payload, touch the
    record, then run the kind's optional `_on_remove` hook (a no-op
    unless a kind needs extra side effects beyond the edit itself)
    -- if that hook returns an error message, fail with it instead
    of reporting success. A kind that hasn't defined `_remove`
    refuses immediately, without attempting to resolve a target at
    all; one whose remove doesn't fit this shape overrides `remove`
    directly instead of defining `_remove`.
    """

    def remove(self, target, arg2=None):
        """
        Resolve the target and delegate the edit to `_remove`.
        """
        if type(self)._remove is Remove._remove:
            raise ValueError(f"{self.kind} does not support remove")
        memory_target = self._resolve_target(target)
        fields = self._remove(memory_target.project_path, arg2)
        self._touch(memory_target)
        error = self._on_remove(memory_target, fields)
        if error:
            self._fail(error)
        self._ok("remove", path=memory_target.project_path, **fields)

    def _remove(self, path, arg2):
        raise ValueError(f"{self.kind} does not support remove")

    def _on_remove(self, memory_target, fields):
        return None
