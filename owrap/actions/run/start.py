class Start:
    """
    Default `start`: delegate to the kind's `_on_start` callback for
    its payload, then report success. A kind that hasn't defined
    `_on_start` refuses immediately.
    """

    def start(self) -> None:
        """
        Delegate to `_on_start` and report success.
        """
        if type(self)._on_start is Start._on_start:
            raise ValueError(f"{self.kind} does not support start")
        self._ok("start", **self._on_start())

    def _on_start(self) -> dict:
        raise ValueError(f"{self.kind} does not support start")
