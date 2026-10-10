class Set:
    """
    Exposes `set`, refusing by default. Skeleton for now -- no kind
    uses it yet.
    """

    def set(self, *args):
        raise ValueError(f"{self.kind} does not support set")
