class Clean:
    """
    Default `clean`: delegate to the kind's `_on_clean` callback for
    its payload, then report success. A kind that hasn't defined
    `_on_clean` refuses immediately.
    """

    def clean(self, *args) -> None:
        """
        Delegate to `_on_clean` and report success.
        """
        if type(self)._on_clean is Clean._on_clean:
            raise ValueError(f"{self.kind} does not support clean")
        self._ok("clean", **self._on_clean(*args))

    def _on_clean(self, *args) -> dict:
        raise ValueError(f"{self.kind} does not support clean")
