"""
Atomic file writes, shared by any kind that edits a file in place.
"""
import os
import tempfile
from pathlib import Path


def write_atomic(path: Path, content: str) -> None:
    """
    Write `content` to `path` atomically: write to a temp file in
    the same directory, copy over the original's permissions, then
    rename over it.
    """
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(content)
        os.chmod(tmp, path.stat().st_mode)
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)
