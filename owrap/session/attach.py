import os
import sys

from .orientation import print_orientation
from ..utils.session.resolver import (
    _parse, print_known_sessions, resolve_session_or_exit,
    session_file, update_session_field,
)
from ..utils.session.resolver import attach as _attach_pointer
from ..utils.memory.records import resolve_memory_target
from ..utils.paths import _read_config, context_path, get_plan_path, session_input


def _orientation_target(session_id):
    data = _parse(session_file(session_id))
    if not data.get("target_kind"):
        return None
    try:
        return resolve_memory_target(data, allow_missing=True)
    except (OSError, ValueError):
        return None


def attach(session, target_session_id: str = None) -> None:
    """
    Attach to the given session id, project id, or repository id,
    re-export its environment variables, and print its orientation
    banner.
    """
    if not target_session_id:
        print(
            "ERROR: owrap session attach <session_id|project|repository> "
            "-- missing target.",
        )
        print()
        print_known_sessions()
        sys.exit(2)

    resolved_sid = resolve_session_or_exit(
        target_session_id, print_known_on_none=True,
    )

    try:
        sid, sf, prev = _attach_pointer(resolved_sid)
    except (FileNotFoundError, RuntimeError) as exc:
        session._fail(exc)

    data = _parse(sf)
    url = data.get("server_url", "")
    if data.get("target_kind"):
        for field in ("research", "area", "child"):
            update_session_field(sid, field, "")

    ccsid = os.environ.get("CLAUDE_CODE_SESSION_ID", "").strip()
    cid = os.environ.get("CODEX_SESSION_ID", "").strip()
    if ccsid or cid:
        from ..ctx.state import register_ctx_state_window
        register_ctx_state_window(
            sid, ccsid or cid, harness="claude" if ccsid else "codex",
        )

    plan_path = get_plan_path(sid)
    input_path = session_input(sid)
    cp = context_path(sid)

    print(f"ATTACHED session={sid}  prev_session_for_this_window={prev or '-'}")
    print_orientation(
        sid, url, plan_path, input_path,
        context_path=cp, attach=True,
        runner_enabled=_read_config().get("owrap_runner_enabled", True),
        target=_orientation_target(sid),
    )
    print(f"\n__OWRAP_EXPORT__ SESSION_ID={sid}")
