class Add:
    """
    Default `add`: resolve the target, run the kind's `_add`
    callback for the edit, touch the record, then run the optional
    `_on_add` hook, failing with its message if it returns one. A kind
    without `_add` refuses before resolving a target.
    """

    def add(self, target, arg2=None, arg3=None):
        """
        Resolve the target and delegate the edit to `_add`.
        """
        if type(self)._add is Add._add:
            raise ValueError(f"{self.kind} does not support add")
        memory_target = self._resolve_target(target, write=True)
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
