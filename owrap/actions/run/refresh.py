class Refresh:
    """
    Default `refresh`: delegate to the kind's `_on_refresh` callback
    for its payload, then report success. A kind that hasn't defined
    `_on_refresh` refuses immediately.
    """

    def refresh(self, *args) -> None:
        """
        Delegate to `_on_refresh` and report success.
        """
        if type(self)._on_refresh is Refresh._on_refresh:
            raise ValueError(f"{self.kind} does not support refresh")
        self._ok("refresh", **self._on_refresh(*args))

    def _on_refresh(self, *args) -> dict:
        raise ValueError(f"{self.kind} does not support refresh")
