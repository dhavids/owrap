"""
Context hand-off when a session changes subproject: refuse the
switch while useful transcript is unrecorded, and drop the leftover
transcript whenever a switch goes ahead.
"""
import time

from . import state
from .dispatch import CTX_MIN_CHARS, _pending_excerpt_len
from ..utils.paths import (
    claude_transcript_path, codex_transcript_path, get_workspace_path,
)
from ..utils.session.resolver import (
    all_attached_codex_session_id_pairs, attached_ccsids,
)


def check_switch(session_id: str, force: bool = False) -> None:
    """
    Raise ValueError when an attached window holds at least
    `CTX_MIN_CHARS` of unrecorded transcript.
    """
    if force:
        return
    pending = max((size for _, _, size in _pending(session_id)), default=0)
    if pending < CTX_MIN_CHARS:
        return
    if state.ctx_dispatch_status(session_id) == "running":
        raise ValueError(
            f"a context update is running and {pending} chars of work are "
            "unrecorded. Wait for it to finish before switching, or pass "
            "'force' to discard them."
        )
    raise ValueError(
        f"{pending} chars of work are unrecorded. Run `owrap ctx start` or "
        "`owrap updr start --ctx` (or `--ctx manual` while opencode is "
        "down) before switching, or pass 'force' to discard them."
    )


def reset_windows(session_id: str) -> None:
    """
    Move each attached window's transcript cursor to now and clear a
    failed ctx status.
    """
    now_ns = time.time_ns()
    for window_id, _, _ in _pending(session_id):
        counters = state.read_window_state(session_id, window_id)
        counters["transcript_cursor_ns"] = now_ns
        state.write_window_state(session_id, counters, window_id)
    state.clear_ctx_failure(session_id)


def _pending(session_id: str) -> list:
    workspace = get_workspace_path()
    windows = [
        (ccsid, "claude", claude_transcript_path(ccsid, workspace))
        for ccsid in attached_ccsids(session_id)
    ]
    windows += [
        (cid, "codex", codex_transcript_path(cid))
        for cid, sid in all_attached_codex_session_id_pairs()
        if sid == session_id
    ]
    pending = []
    for window_id, source, path in windows:
        if path is None or not path.exists():
            continue
        lines = path.read_text().splitlines()
        size = _pending_excerpt_len(session_id, window_id, lines, source)
        pending.append((window_id, source, size))
    return pending
