import difflib
import os
import secrets
import sys
import time
from pathlib import Path

from ..paths import SESSION_DIR

SESSIONS_DIR = SESSION_DIR / "sessions"
BY_CCSID_DIR = SESSIONS_DIR / "by_ccsid"
BY_OPENCODE_RUN_ID_DIR = SESSIONS_DIR / "by_opencode_run_id"


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


def opencode_run_id_pointer(oid: str) -> Path:
    return BY_OPENCODE_RUN_ID_DIR / oid


def mint_session_id() -> str:
    return secrets.token_hex(3)


def owrap_sid_for_ccsid(ccsid: str) -> str | None:
    """
    Resolve the owrap session id a given ccsid is attached to.

    Looks up the by_ccsid/<ccsid> pointer directly rather than scanning
    .session files for a claude_session_id field match — under multi-attach,
    that field only ever holds the most recently attached ccsid, so a scan
    silently misses every other window attached to the same session.
    """
    if not ccsid:
        return None
    ptr = ccsid_pointer(ccsid)
    if ptr.exists():
        return ptr.read_text().strip() or None
    return None


def list_sessions() -> list:
    """
    Return list of {session_id, claude_session_id, opencode_run_id,
    research, started, last_refresh, owned_by_current}.
    """
    out = []
    cur_ccsid = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    cur_oid = os.environ.get("OPENCODE_RUN_ID", "")
    if SESSIONS_DIR.exists():
        for sf in sorted(SESSIONS_DIR.glob("*.session")):
            d = _parse(sf)
            sid = d.get("session_id") or sf.stem
            d["session_id"] = sid
            owned_by_ccsid = (cur_ccsid and d.get("claude_session_id") == cur_ccsid)
            owned_by_oid = (cur_oid and d.get("opencode_run_id") == cur_oid)
            d["owned_by_current"] = owned_by_ccsid or owned_by_oid
            out.append(d)
    return out


def resolve(mode: str) -> tuple:
    """Resolve session_id for current call.
    Returns (session_id, session_file_path, source).

    mode='start':   env SESSION_ID -> by_ccsid -> MINT new (writes both files).
    mode='refresh': env SESSION_ID -> by_ccsid -> returns (None, None, 'missing').
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

    oid = os.environ.get("OPENCODE_RUN_ID", "").strip()
    if oid:
        ptr = opencode_run_id_pointer(oid)
        if ptr.exists():
            sid = ptr.read_text().strip()
            sf = session_file(sid)
            if sf.exists():
                return sid, sf, "opencode_run_id"
            # stale pointer; clean it
            ptr.unlink(missing_ok=True)

    if mode == "start":
        sid = mint_session_id()
        sf = session_file(sid)
        data = {
            "session_id": sid,
            "claude_session_id": ccsid,
            "opencode_run_id": oid,
            "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        _write(sf, data)
        if ccsid:
            BY_CCSID_DIR.mkdir(parents=True, exist_ok=True)
            ccsid_pointer(ccsid).write_text(sid)
        if oid:
            BY_OPENCODE_RUN_ID_DIR.mkdir(parents=True, exist_ok=True)
            opencode_run_id_pointer(oid).write_text(sid)
        return sid, sf, "minted"

    return None, None, "missing"


def _bind_anchor(
    target_sid: str,
    env_value: str,
    pointer_dir: Path,
    pointer_path: Path,
    session_key: str,
) -> str | None:
    """
    Bind target_sid to an environment anchor (CCSID or OPENCODE_RUN_ID).

    Many anchors of the same type may point at target_sid at once (multi-
    attach); each individual anchor still points at only one session, so
    binding it elsewhere first releases its previous session.

    Returns the previous session id pointed at by this anchor, if any.
    """
    if not env_value:
        return None
    pointer_dir.mkdir(parents=True, exist_ok=True)

    # Release current anchor from any session it currently points at (1-1 the other way)
    prev_sid = None
    if pointer_path.exists():
        prev_sid = pointer_path.read_text().strip()
        if prev_sid and prev_sid != target_sid:
            prev_sf = session_file(prev_sid)
            if prev_sf.exists():
                d = _parse(prev_sf)
                d[session_key] = ""
                _write(prev_sf, d)

    # Write new pointer
    pointer_path.write_text(target_sid)
    return prev_sid


def _clear_anchor(target_sid: str, pointer_dir: Path):
    """
    Remove any pointer under pointer_dir that currently references target_sid.
    """
    if not pointer_dir.exists():
        return
    for ptr in pointer_dir.iterdir():
        if ptr.is_file() and ptr.read_text().strip() == target_sid:
            ptr.unlink(missing_ok=True)


def attached_ccsids(session_id: str) -> list:
    """
    Return every ccsid whose by_ccsid pointer currently targets session_id.
    """
    if not BY_CCSID_DIR.exists():
        return []
    return [
        p.name for p in BY_CCSID_DIR.iterdir()
        if p.is_file() and p.read_text().strip() == session_id
    ]


def all_attached_ccsid_pairs() -> list:
    """
    Return (ccsid, owrap_sid) for every currently-attached window, across
    every owrap session — the reverse direction of `attached_ccsids`.
    """
    if not BY_CCSID_DIR.exists():
        return []
    pairs = []
    for p in BY_CCSID_DIR.iterdir():
        if not p.is_file():
            continue
        sid = p.read_text().strip()
        if sid:
            pairs.append((p.name, sid))
    return pairs


def _suggest_attach_targets(token: str, sessions: list) -> list:
    """
    Return session/research/area strings close to token, for a
    "did you mean" hint when no exact match was found.
    """

    candidates = set()
    for s in sessions:
        candidates.add(s.get("session_id", ""))
        candidates.add(s.get("research", ""))
        candidates.add(s.get("area", ""))
    candidates.discard("")

    substring = [c for c in candidates if token.lower() in c.lower()]
    close = difflib.get_close_matches(token, candidates, n=5, cutoff=0.6)

    ordered = []
    for c in substring + close:
        if c not in ordered:
            ordered.append(c)
    return ordered[:5]


def resolve_attach_target(token: str) -> tuple:
    """
    Resolve a user-typed `owrap attach` argument to a session.

    Tries an exact session id first, then an exact match on the
    'research' field, then an exact match on the 'area' field;
    research and area hits are unioned and deduped by session_id.

    Returns (status, payload):
      ("session_id", token) — token is a valid session id
      ("unique", session_dict) — exactly one session matched
      ("ambiguous", (differential, [session_dicts])) — 2+ matched
      ("none", [suggestions]) — no match; near-miss strings, if any
    """
    if session_file(token).exists():
        return "session_id", token

    sessions = list_sessions()
    research_matches = [s for s in sessions if s.get("research") == token]
    area_matches = [s for s in sessions if s.get("area") == token]

    seen = {}
    for s in research_matches + area_matches:
        seen[s["session_id"]] = s
    matches = list(seen.values())

    if not matches:
        return "none", _suggest_attach_targets(token, sessions)
    if len(matches) == 1:
        return "unique", matches[0]

    researches = {s.get("research", "") for s in matches}
    areas = {s.get("area", "") for s in matches}
    if len(researches) == 1 and len(areas) > 1:
        differential = "area"
    elif len(areas) == 1 and len(researches) > 1:
        differential = "research"
    else:
        differential = "multi"

    matches.sort(key=lambda s: (s.get("research", ""), s.get("area", "")))
    return "ambiguous", (differential, matches)


def format_ambiguous_attach_error(target: str, differential: str, matches: list) -> str:
    """
    Format the standard AMBIGUOUS error for a resolve_attach_target()
    ambiguous result, listing each match by its differing field and
    session id so the caller knows what to re-run with.
    """
    lines = [
        f"AMBIGUOUS: '{target}' matches {len(matches)} sessions "
        f"(differing by {differential}) - results:",
    ]
    for s in matches:
        if differential == "area":
            label = s.get("area", "-")
        elif differential == "research":
            label = s.get("research", "-")
        else:
            label = f"research={s.get('research', '-')} area={s.get('area', '-')}"
        lines.append(f"  {label:<24} session={s['session_id']}")
    return "\n".join(lines)


def print_known_sessions():
    """
    Print the session id/research/area table for all known sessions.
    """
    print("Known sessions:")
    for s in list_sessions():
        ccsid_val = s.get("claude_session_id", "-")
        _cc = ccsid_val[:8] if ccsid_val != "-" else "-"
        print(
            f"  {s['session_id']}  research={s.get('research', '-')}  "
            f"area={s.get('area', '-')}  started={s.get('started', '-')}  ccsid={_cc}",
        )


def resolve_session_or_exit(token: str, print_known_on_none: bool = False) -> str:
    """
    Resolve a user-typed session id/research/area target to a session id,
    printing the standard error and exiting(2) on an unknown or ambiguous
    match. The single point every caller should go through instead of
    branching on resolve_attach_target()'s status itself.
    """
    status, payload = resolve_attach_target(token)
    if status == "session_id":
        return token
    if status == "unique":
        return payload["session_id"]
    if status == "none":
        print(f"ERROR: no session found matching '{token}'.")
        if payload:
            print(f"Did you mean: {', '.join(payload)}?")
        if print_known_on_none:
            print()
            print_known_sessions()
        sys.exit(2)
    differential, matches = payload
    print(format_ambiguous_attach_error(token, differential, matches))
    sys.exit(2)


def attach(target_sid: str) -> tuple:
    """
    Bind target_sid to the caller's identity anchor.

    Priority: ccsid (CLAUDE_CODE_SESSION_ID) > oid (OPENCODE_RUN_ID) > parent
    PID (same-call fallback only — never persisted as a resolvable pointer).
    Multiple ccsids (or multiple oids) may attach to the same target_sid at
    once — multi-attach is allowed within one anchor type. Whichever anchor
    type wins for this call, any existing pointer of the OTHER type that
    references this session is cleared, and its field in the session file is
    cleared too — a session is claimed by one anchor type at a time, ccsid or
    oid, never both.

    Returns (target_sid, target_session_file, prev_sid_for_the_winning_anchor).
    Raises FileNotFoundError if target session file missing.
    """
    ccsid = os.environ.get("CLAUDE_CODE_SESSION_ID", "").strip()
    oid = os.environ.get("OPENCODE_RUN_ID", "").strip()
    sf = session_file(target_sid)
    if not sf.exists():
        raise FileNotFoundError(f"session not found: {target_sid}")

    d = _parse(sf)
    prev_sid = None

    if ccsid:
        prev_sid = _bind_anchor(
            target_sid, ccsid, BY_CCSID_DIR,
            ccsid_pointer(ccsid), "claude_session_id",
        )
        _clear_anchor(target_sid, BY_OPENCODE_RUN_ID_DIR)
        d["claude_session_id"] = ccsid
        d["opencode_run_id"] = ""
    elif oid:
        prev_sid = _bind_anchor(
            target_sid, oid, BY_OPENCODE_RUN_ID_DIR,
            opencode_run_id_pointer(oid), "opencode_run_id",
        )
        _clear_anchor(target_sid, BY_CCSID_DIR)
        d["opencode_run_id"] = oid
        d["claude_session_id"] = ""
    else:
        _clear_anchor(target_sid, BY_CCSID_DIR)
        _clear_anchor(target_sid, BY_OPENCODE_RUN_ID_DIR)
        d["claude_session_id"] = ""
        d["opencode_run_id"] = ""
        d["attached_ppid"] = str(os.getppid())

    d["last_attach"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    _write(sf, d)
    return target_sid, sf, prev_sid


def detach() -> str | None:
    """
    Release the caller's ccsid/oid pointer from whatever session it is
    attached to, leaving any other window still attached to that session
    untouched.

    Returns the session id detached from, or None if not attached to any.
    """
    ccsid = os.environ.get("CLAUDE_CODE_SESSION_ID", "").strip()
    oid = os.environ.get("OPENCODE_RUN_ID", "").strip()

    sid = None
    if ccsid:
        ptr = ccsid_pointer(ccsid)
        if ptr.exists():
            sid = ptr.read_text().strip()
            ptr.unlink(missing_ok=True)
    if not sid and oid:
        ptr = opencode_run_id_pointer(oid)
        if ptr.exists():
            sid = ptr.read_text().strip()
            ptr.unlink(missing_ok=True)
    if not sid:
        return None

    sf = session_file(sid)
    if sf.exists():
        d = _parse(sf)
        if ccsid and d.get("claude_session_id") == ccsid:
            remaining = [c for c in attached_ccsids(sid) if c != ccsid]
            d["claude_session_id"] = remaining[-1] if remaining else ""
        if oid and d.get("opencode_run_id") == oid:
            d["opencode_run_id"] = ""
        _write(sf, d)
    return sid


def update_session_field(session_id: str, key: str, value: str):
    """
    Set/update a single field in a session file.
    """
    sf = session_file(session_id)
    if not sf.exists():
        return
    d = _parse(sf)
    d[key] = value
    _write(sf, d)


def remove_session(session_id: str):
    """
    Delete session file and any by_ccsid or by_opencode_run_id pointers
    referencing it. Caller handles plan/context/input cleanup.
    """
    sf = session_file(session_id)
    if sf.exists():
        sf.unlink(missing_ok=True)
    for pointer_dir in (BY_CCSID_DIR, BY_OPENCODE_RUN_ID_DIR):
        if pointer_dir.exists():
            for ptr in pointer_dir.iterdir():
                if ptr.is_file() and ptr.read_text().strip() == session_id:
                    ptr.unlink(missing_ok=True)


def migrate_legacy_files():
    """One-shot: detect ~/.owrap/sessions/<CCSID-format>.session files
    (UUID-style names) and convert.

    Old format: file named after CCSID (UUID-ish: 8-4-4-4-12),
    contains session_id=<hex>.
    New format: file named after session_id (6 hex), has
    claude_session_id=<CCSID> field, plus by_ccsid/<CCSID> pointer.
    """
    import re as _re
    uuid_re = _re.compile(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    )
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
