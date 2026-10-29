class Set:
    """
    Exposes `set`, refusing by default. No kind uses it yet.
    """

    def set(self, *args):
        raise ValueError(f"{self.kind} does not support set")
