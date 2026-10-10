class Wait:
    """
    Default `wait`: delegate to the kind's `_on_wait` callback to
    block until some event of its own finishes (or fail on timeout),
    then report success. A kind that hasn't defined `_on_wait`
    refuses immediately.
    """

    def wait(self, *args) -> None:
        """
        Delegate to `_on_wait` and report success.
        """
        if type(self)._on_wait is Wait._on_wait:
            raise ValueError(f"{self.kind} does not support wait")
        self._ok("wait", **self._on_wait(*args))

    def _on_wait(self, *args) -> dict:
        raise ValueError(f"{self.kind} does not support wait")
