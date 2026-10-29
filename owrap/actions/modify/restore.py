class Restore:
    """
    Exposes `restore`, refusing by default. No kind uses it yet.
    """

    def restore(self, *args):
        raise ValueError(f"{self.kind} does not support restore")
