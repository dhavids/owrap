class Detach:
    """
    Default `detach`: delegate to the kind's `_on_detach` callback
    for its payload, then report success. A kind that hasn't defined
    `_on_detach` refuses immediately.
    """

    def detach(self, *args) -> None:
        """
        Delegate to `_on_detach` and report success.
        """
        if type(self)._on_detach is Detach._on_detach:
            raise ValueError(f"{self.kind} does not support detach")
        self._ok("detach", **self._on_detach(*args))

    def _on_detach(self, *args) -> dict:
        raise ValueError(f"{self.kind} does not support detach")
