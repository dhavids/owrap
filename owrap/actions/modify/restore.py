class Restore:
    """
    Exposes `restore`, refusing by default. Skeleton for now -- no
    kind uses it yet.
    """

    def restore(self, *args):
        raise ValueError(f"{self.kind} does not support restore")
