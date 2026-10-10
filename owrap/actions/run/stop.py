class Stop:
    """
    Default `stop`: delegate to the kind's `_on_stop` callback for
    its payload, then report success. A kind that hasn't defined
    `_on_stop` refuses immediately.
    """

    def stop(self, *args) -> None:
        """
        Delegate to `_on_stop` and report success.
        """
        if type(self)._on_stop is Stop._on_stop:
            raise ValueError(f"{self.kind} does not support stop")
        self._ok("stop", **self._on_stop(*args))

    def _on_stop(self, *args) -> dict:
        raise ValueError(f"{self.kind} does not support stop")
