class Kill:
    """
    Default `kill`: delegate to the kind's `_on_kill` callback for
    its payload, then report success. A kind that hasn't defined
    `_on_kill` refuses immediately.
    """

    def kill(self, *args) -> None:
        """
        Delegate to `_on_kill` and report success.
        """
        if type(self)._on_kill is Kill._on_kill:
            raise ValueError(f"{self.kind} does not support kill")
        self._ok("kill", **self._on_kill(*args))

    def _on_kill(self, *args) -> dict:
        raise ValueError(f"{self.kind} does not support kill")
