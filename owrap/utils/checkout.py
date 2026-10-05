from pathlib import Path


def is_development(root: Path) -> bool:
    """
    Return whether a checkout lives in the workspace development directory.
    """
    return root.resolve().parent.name == "dev"


def live_checkout(root: Path) -> Path:
    """
    Return the matching live checkout for a development checkout.
    """
    root = root.resolve()
    if not is_development(root):
        return root
    return root.parent.parent / root.name
