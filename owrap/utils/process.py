"""
Process inspection helpers.
"""

import os


def is_alive(pid: int) -> bool:
    """
    Return whether a process is still running.
    """
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False
