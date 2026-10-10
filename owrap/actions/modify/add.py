class Add:
    """
    Default `add`: resolve the target, hand the actual edit off to
    the kind's `_add` callback for its payload, touch the record,
    then run the kind's optional `_on_add` hook (a no-op unless a
    kind needs extra side effects beyond the edit itself) -- if that
    hook returns an error message, fail with it instead of reporting
    success. A kind that hasn't defined `_add` refuses immediately,
    without attempting to resolve a target at all; one whose add
    doesn't fit this shape overrides `add` directly instead of
    defining `_add`.
    """

    def add(self, target, arg2=None, arg3=None):
        """
        Resolve the target and delegate the edit to `_add`.
        """
        if type(self)._add is Add._add:
            raise ValueError(f"{self.kind} does not support add")
        memory_target = self._resolve_target(target)
        fields = self._add(memory_target.project_path, arg2, arg3)
        self._touch(memory_target)
        error = self._on_add(memory_target, fields)
        if error:
            self._fail(error)
        self._ok("add", path=memory_target.project_path, **fields)

    def _add(self, path, arg2, arg3):
        raise ValueError(f"{self.kind} does not support add")

    def _on_add(self, memory_target, fields):
        return None
