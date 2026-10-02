import fcntl
import os
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def file_lock(lock_path: Path, shared: bool = False):
    """
    Hold an flock on lock_path for the duration of the with-block.

    Creates lock_path (and its parent directory) if missing. Use
    shared=True for a read lock that may coexist with other readers.
    """
    lock_path = Path(lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_CREAT | os.O_WRONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_SH if shared else fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
