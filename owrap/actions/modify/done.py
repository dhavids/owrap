class Done:
    """
    Default `done`: resolve the target, hand the actual edit off to
    the kind's `_done` callback for its payload, touch the record,
    then run the kind's optional `_on_done` hook (a no-op unless a
    kind needs extra side effects beyond the edit itself) -- if that
    hook returns an error message, fail with it instead of reporting
    success. A kind that hasn't defined `_done` refuses immediately,
    without attempting to resolve a target at all; one whose done
    doesn't fit this shape (e.g. a live process/session kind ending
    a session) overrides `done` directly instead of defining
    `_done`.
    """

    def done(self, target, arg2=None):
        """
        Resolve the target and delegate the edit to `_done`.
        """
        if type(self)._done is Done._done:
            raise ValueError(f"{self.kind} does not support done")
        memory_target = self._resolve_target(target)
        fields = self._done(memory_target.project_path, arg2)
        self._touch(memory_target)
        error = self._on_done(memory_target, fields)
        if error:
            self._fail(error)
        self._ok("done", path=memory_target.project_path, **fields)

    def _done(self, path, arg2):
        raise ValueError(f"{self.kind} does not support done")

    def _on_done(self, memory_target, fields):
        return None
