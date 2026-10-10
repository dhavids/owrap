class Attach:
    """
    Default `attach`: delegate to the kind's `_on_attach` callback
    for its payload, then report success. A kind that hasn't defined
    `_on_attach` refuses immediately.
    """

    def attach(self, *args) -> None:
        """
        Delegate to `_on_attach` and report success.
        """
        if type(self)._on_attach is Attach._on_attach:
            raise ValueError(f"{self.kind} does not support attach")
        self._ok("attach", **self._on_attach(*args))

    def _on_attach(self, *args) -> dict:
        raise ValueError(f"{self.kind} does not support attach")
