import fcntl
import json
import os
import time
from contextlib import contextmanager
from datetime import datetime

from .paths import (
    RUNTIME_LOG, RUNTIME_LOG_MAX_BYTES, RUNTIME_LOG_GENERATIONS,
)

_MAX_LINE = 3900
_SIZE_CHECK_EVERY = 200

_fd = None
_write_count = 0


def _open():
    global _fd
    if _fd is not None:
        return _fd
    RUNTIME_LOG.parent.mkdir(parents=True, exist_ok=True)
    _fd = os.open(
        str(RUNTIME_LOG), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644,
    )
    return _fd


@contextmanager
def _lock(fd):
    acquired = False
    for _ in range(5):
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
            break
        except OSError:
            time.sleep(0.01)
    try:
        yield
    finally:
        # Non-blocking flock with 0_APPEND fallback guarantee
        if acquired:
            fcntl.flock(fd, fcntl.LOCK_UN)


def _maybe_rotate(fd):
    global _fd
    if _write_count % _SIZE_CHECK_EVERY != 0:
        return fd
    try:
        st = os.fstat(fd)
    except OSError:
        return fd
    if st.st_size <= RUNTIME_LOG_MAX_BYTES:
        return fd
    base = str(RUNTIME_LOG)
    for i in range(RUNTIME_LOG_GENERATIONS - 1, 0, -1):
        src = f"{base}.{i}"
        dst = f"{base}.{i + 1}"
        if os.path.exists(src):
            os.replace(src, dst)
    os.replace(base, f"{base}.1")
    try:
        os.close(fd)
    except OSError:
        pass
    _fd = None
    return _open()


def log(event, **fields):
    """
    Append a JSONL event to the runtime log, rotating it once it exceeds
    the configured size.
    """
    global _write_count
    if os.environ.get("OWRAP_TEST_MODE"):
        return
    try:
        fd = _open()
        _write_count += 1
        sid = os.environ.get("OWRAP_SESSION_ID") or os.environ.get(
            "SESSION_ID", "",
        ) or ""
        obj = {
            "ts": datetime.now().isoformat(timespec="milliseconds"),
            "pid": os.getpid(),
            "sid": sid,
            "ev": event,
            **fields,
        }
        line = json.dumps(obj, default=str)
        if len(line) > _MAX_LINE:
            longest_key = max(fields, key=lambda k: len(str(fields[k])))
            val = str(fields[longest_key])
            over = len(line) - _MAX_LINE
            obj[longest_key] = val[:-over]
            line = json.dumps(obj, default=str)
        line += "\n"
        with _lock(fd):
            fd = _maybe_rotate(fd)
            os.write(fd, line.encode())
    except Exception:
        pass


@contextmanager
def timed(event, **fields):
    """
    Context manager that logs `event` with a `dur_s` field for the wrapped
    block's duration.
    """
    holder = {}
    start = time.time()
    try:
        yield holder
    finally:
        elapsed = round(time.time() - start, 2)
        out = dict(fields)
        out.update(holder)
        out["dur_s"] = elapsed
        log(event, **out)
