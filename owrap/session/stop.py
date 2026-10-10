from ..utils.paths import SESSION_DIR
from ..utils.session.resolver import (
    resolve, remove_session, BY_CCSID_DIR, list_sessions,
    _parse as _parse_session,
)
from ..utils.session.trash import move_to_trash


def stop(target: str = None) -> tuple:
    """
    Stop the current (or named) session and move it to the trash.
    Returns (message, stopped) -- stopped is False when there was no
    matching/current session to stop at all.
    """
    sid = None

    if target:
        for s in list_sessions():
            matches = (
                s["session_id"].startswith(target)
                or s.get("project_id", "") == target
            )
            if matches:
                sid = s["session_id"]
                break
        if sid is None:
            return (
                f"OWRAP STOP: no session matching '{target}'. "
                "Use `owrap session stop force` to clear everything.",
                False,
            )
    else:
        sid, _, _ = resolve(mode="refresh")

    if sid is None:
        return (
            "OWRAP STOP: no current session to stop. "
            "Use `owrap session stop force` to clear everything.",
            False,
        )

    move_to_trash(sid)
    remove_session(sid)

    other_sessions = [s["session_id"] for s in list_sessions() if s["session_id"] != sid]
    n = len(other_sessions)
    if n:
        plural = "s" if n != 1 else ""
        return f"OWRAP SESSION ENDED  ({n} other session{plural} active)", True
    return "OWRAP STOPPED  no other sessions", True


def force_stop() -> int:
    """
    Move every session to the trash -- including the global session
    pointer -- and clear every CCSID attachment pointer. Returns the
    number of sessions moved. Does not touch servers/tasks/daemon;
    callers combine this with a kill step for the full `stop force`.
    """
    count = 0
    for s in list_sessions():
        move_to_trash(s["session_id"])
        remove_session(s["session_id"])
        count += 1

    global_session = SESSION_DIR / "session"
    if global_session.exists():
        data = _parse_session(global_session)
        gsid = data.get("session_id", "")
        global_session.unlink(missing_ok=True)
        if gsid:
            move_to_trash(gsid)
        count += 1

    if BY_CCSID_DIR.exists():
        for ptr in BY_CCSID_DIR.iterdir():
            if ptr.is_file():
                ptr.unlink(missing_ok=True)

    return count
