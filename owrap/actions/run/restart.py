class Restart:
    """
    Default `restart`: delegate to the kind's `_on_restart` callback
    for its payload, then report success. A kind that hasn't defined
    `_on_restart` refuses immediately.
    """

    def restart(self) -> None:
        """
        Delegate to `_on_restart` and report success.
        """
        if type(self)._on_restart is Restart._on_restart:
            raise ValueError(f"{self.kind} does not support restart")
        self._ok("restart", **self._on_restart())

    def _on_restart(self) -> dict:
        raise ValueError(f"{self.kind} does not support restart")
