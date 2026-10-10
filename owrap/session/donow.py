from ..utils.constants import NO_CONTEXT_MSG
from ..utils.paths import context_path


def check_donow(session_id: str) -> str | None:
    """
    Return recovery instructions when the session context is missing.
    """
    cp = context_path(session_id)
    if not cp.exists():
        return NO_CONTEXT_MSG.format(sid=session_id)
    return None
