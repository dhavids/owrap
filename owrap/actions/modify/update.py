class Update:
    """
    Default `update`: resolve the target, run the kind's `_update`
    callback for the edit, touch the record, then run the optional
    `_on_update` hook, failing with its message if it returns one. A kind
    without `_update` refuses before resolving a target.
    """

    def update(self, target, arg2=None, arg3=None):
        """
        Resolve the target and delegate the edit to `_update`.
        """
        if type(self)._update is Update._update:
            raise ValueError(f"{self.kind} does not support update")
        memory_target = self._resolve_target(target, write=True)
        fields = self._update(memory_target.project_path, arg2, arg3)
        self._touch(memory_target)
        error = self._on_update(memory_target, fields)
        if error:
            self._fail(error)
        self._ok("update", path=memory_target.project_path, **fields)

    def _update(self, path, arg2, arg3):
        raise ValueError(f"{self.kind} does not support update")

    def _on_update(self, memory_target, fields):
        return None
