class Update:
    """
    Default `update`: resolve the target, hand the actual edit off to
    the kind's `_update` callback for its payload, touch the record,
    then run the kind's optional `_on_update` hook (a no-op unless a
    kind needs extra side effects beyond the edit itself) -- if that
    hook returns an error message, fail with it instead of reporting
    success. A kind that hasn't defined `_update` refuses immediately,
    without attempting to resolve a target at all; one whose update
    doesn't fit this shape overrides `update` directly instead of
    defining `_update`.
    """

    def update(self, target, arg2=None, arg3=None):
        """
        Resolve the target and delegate the edit to `_update`.
        """
        if type(self)._update is Update._update:
            raise ValueError(f"{self.kind} does not support update")
        memory_target = self._resolve_target(target)
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
