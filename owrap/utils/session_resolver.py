import os
import secrets
import time
from pathlib import Path

SESSIONS_DIR = Path.home() / ".owrap" / "sessions"
BY_CCSID_DIR = SESSIONS_DIR / "by_ccsid"


def _parse(path: Path) -> dict:
    data = {}
    try:
        for line in path.read_text().splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                data[k.strip()] = v.strip()
    except Exception:
        pass
    return data


def _write(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{k}={v}" for k, v in data.items() if v is not None]
    path.write_text("\n".join(lines) + "\n")


def session_file(session_id: str) -> Path:
    return SESSIONS_DIR / f"{session_id}.session"


def ccsid_pointer(ccsid: str) -> Path:
    return BY_CCSID_DIR / ccsid


def mint_session_id() -> str:
    return secrets.token_hex(3)


def list_sessions() -> list:
    """Return list of {session_id, claude_session_id, research, started, last_refresh, owned_by_current}."""
    out = []
    cur_ccsid = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    if SESSIONS_DIR.exists():
        for sf in sorted(SESSIONS_DIR.glob("*.session")):
            d = _parse(sf)
            sid = d.get("session_id") or sf.stem
            d["session_id"] = sid
            d["owned_by_current"] = (cur_ccsid and d.get("claude_session_id") == cur_ccsid)
            out.append(d)
    return out


def resolve(mode: str) -> tuple:
    """Resolve session_id for current call. Returns (session_id, session_file_path, source).

    mode='start':   env SESSION_ID → by_ccsid → MINT new (writes both files).
    mode='refresh': env SESSION_ID → by_ccsid → returns (None, None, 'missing').
    """
    env_sid = os.environ.get("SESSION_ID", "").strip()
    ccsid = os.environ.get("CLAUDE_CODE_SESSION_ID", "").strip()

    if env_sid:
        sf = session_file(env_sid)
        if sf.exists():
            return env_sid, sf, "env"

    if ccsid:
        ptr = ccsid_pointer(ccsid)
        if ptr.exists():
            sid = ptr.read_text().strip()
            sf = session_file(sid)
            if sf.exists():
                return sid, sf, "ccsid"
            # stale pointer; clean it
            ptr.unlink(missing_ok=True)

    if mode == "start":
        sid = mint_session_id()
        sf = session_file(sid)
        data = {
            "session_id": sid,
            "claude_session_id": ccsid,
            "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        _write(sf, data)
        if ccsid:
            BY_CCSID_DIR.mkdir(parents=True, exist_ok=True)
            ccsid_pointer(ccsid).write_text(sid)
        return sid, sf, "minted"

    return None, None, "missing"


def attach(target_sid: str) -> tuple:
    """Bind target_sid to current CCSID, enforcing 1-1. Returns (target_sid, target_session_file, prev_sid_for_ccsid).

    Raises FileNotFoundError if target session file missing.
    When CLAUDE_CODE_SESSION_ID is empty, skips ccsid_pointer operations but still updates session file.
    """
    ccsid = os.environ.get("CLAUDE_CODE_SESSION_ID", "").strip()
    sf = session_file(target_sid)
    if not sf.exists():
        raise FileNotFoundError(f"session not found: {target_sid}")

    prev_sid_for_ccsid = None

    if ccsid:
        BY_CCSID_DIR.mkdir(parents=True, exist_ok=True)

        # De-own target_sid from any previous CCSID
        prev_owner = None
        if BY_CCSID_DIR.exists():
            for ptr in BY_CCSID_DIR.iterdir():
                if ptr.is_file() and ptr.read_text().strip() == target_sid and ptr.name != ccsid:
                    prev_owner = ptr.name
                    ptr.unlink(missing_ok=True)

        # Release current CCSID from any session it currently points at (1-1 the other way)
        cur_ptr = ccsid_pointer(ccsid)
        if cur_ptr.exists():
            prev_sid_for_ccsid = cur_ptr.read_text().strip()
            if prev_sid_for_ccsid and prev_sid_for_ccsid != target_sid:
                prev_sf = session_file(prev_sid_for_ccsid)
                if prev_sf.exists():
                    d = _parse(prev_sf)
                    d["claude_session_id"] = ""
                    _write(prev_sf, d)

        # Write new pointer
        cur_ptr.write_text(target_sid)

    # Update target session file
    d = _parse(sf)
    if ccsid:
        d["claude_session_id"] = ccsid
    d["last_attach"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    _write(sf, d)
    return target_sid, sf, prev_sid_for_ccsid


def update_session_field(session_id: str, key: str, value: str):
    """Set/update a single field in a session file."""
    sf = session_file(session_id)
    if not sf.exists():
        return
    d = _parse(sf)
    d[key] = value
    _write(sf, d)


def remove_session(session_id: str):
    """Delete session file + any by_ccsid pointers referencing it. Caller handles plan/context/input cleanup."""
    sf = session_file(session_id)
    if sf.exists():
        sf.unlink(missing_ok=True)
    if BY_CCSID_DIR.exists():
        for ptr in BY_CCSID_DIR.iterdir():
            if ptr.is_file() and ptr.read_text().strip() == session_id:
                ptr.unlink(missing_ok=True)


def migrate_legacy_files():
    """One-shot: detect ~/.owrap/sessions/<CCSID-format>.session files (UUID-style names) and convert.

    Old format: file named after CCSID (UUID-ish: 8-4-4-4-12), contains session_id=<hex>.
    New format: file named after session_id (6 hex), has claude_session_id=<CCSID> field, plus by_ccsid/<CCSID> pointer.
    """
    import re as _re
    uuid_re = _re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
    if not SESSIONS_DIR.exists():
        return 0
    BY_CCSID_DIR.mkdir(parents=True, exist_ok=True)
    converted = 0
    for sf in list(SESSIONS_DIR.glob("*.session")):
        stem = sf.stem
        if not uuid_re.match(stem):
            continue
        d = _parse(sf)
        sid = d.get("session_id")
        if not sid:
            continue
        d["claude_session_id"] = stem
        new_sf = session_file(sid)
        if not new_sf.exists():
            _write(new_sf, d)
        ccsid_pointer(stem).write_text(sid)
        sf.unlink(missing_ok=True)
        converted += 1
    return converted
