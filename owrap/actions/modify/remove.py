class Remove:
    """
    Default `remove`: resolve the target, run the kind's `_remove`
    callback for the edit, touch the record, then run the optional
    `_on_remove` hook, failing with its message if it returns one. A kind
    without `_remove` refuses before resolving a target.
    """

    def remove(self, target, arg2=None):
        """
        Resolve the target and delegate the edit to `_remove`.
        """
        if type(self)._remove is Remove._remove:
            raise ValueError(f"{self.kind} does not support remove")
        memory_target = self._resolve_target(target, write=True)
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
