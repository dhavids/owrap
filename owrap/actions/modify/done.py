class Done:
    """
    Default `done`: resolve the target, run the kind's `_done`
    callback for the edit, touch the record, then run the optional
    `_on_done` hook, failing with its message if it returns one. A kind
    without `_done` refuses before resolving a target.
    """

    def done(self, target, arg2=None):
        """
        Resolve the target and delegate the edit to `_done`.
        """
        if type(self)._done is Done._done:
            raise ValueError(f"{self.kind} does not support done")
        memory_target = self._resolve_target(target, write=True)
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
