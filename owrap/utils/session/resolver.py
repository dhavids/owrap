import difflib
import json
import os
import secrets
import sys
import time
from pathlib import Path

from ..paths import SESSIONS_DIR

SESSION_INDEX_DIR = SESSIONS_DIR / "_index"
BY_CCSID_DIR = SESSION_INDEX_DIR / "claude"
BY_OPENCODE_RUN_ID_DIR = SESSION_INDEX_DIR / "opencode"
BY_CODEX_SESSION_ID_DIR = SESSION_INDEX_DIR / "codex"

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
    return SESSIONS_DIR / session_id / ".session"


def session_files() -> list[Path]:
    """
    Return every current session's metadata file.
    """
    return sorted(SESSIONS_DIR.glob("*/.session"))


def ccsid_pointer(ccsid: str) -> Path:
    return _pointer(BY_CCSID_DIR, ccsid)


def opencode_run_id_pointer(oid: str) -> Path:
    return _pointer(BY_OPENCODE_RUN_ID_DIR, oid)


def codex_session_id_pointer(cid: str) -> Path:
    return _pointer(BY_CODEX_SESSION_ID_DIR, cid)


def _pointer(directory: Path, name: str) -> Path:
    return directory / name


def owrap_sid_for_codex_session_id(cid: str) -> str | None:
    """
    Resolve the owrap session attached to a Codex session.
    """
    if not cid:
        return None
    ptr = codex_session_id_pointer(cid)
    return ptr.read_text().strip() or None if ptr.exists() else None


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
    Return session records with ownership for the current window.
    """
    out = []
    cur_ccsid = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    cur_oid = os.environ.get("OPENCODE_RUN_ID", "")
    cur_cid = os.environ.get("CODEX_SESSION_ID", "")
    if SESSIONS_DIR.exists():
        for sf in session_files():
            d = _parse(sf)
            sid = d.get("session_id") or sf.stem
            d["session_id"] = sid
            owned_by_ccsid = (cur_ccsid and d.get("claude_session_id") == cur_ccsid)
            owned_by_oid = (cur_oid and d.get("opencode_run_id") == cur_oid)
            owned_by_cid = (cur_cid and d.get("codex_session_id") == cur_cid)
            d["owned_by_current"] = owned_by_ccsid or owned_by_oid or owned_by_cid
            out.append(d)
    return out


def _rebind_stale_anchor(sid: str, token: str, pointer_dir: Path, pointer_fn) -> None:
    """
    Point `token`'s anchor at `sid` if it doesn't already.
    """
    ptr = pointer_fn(token)
    current = ptr.read_text().strip() if ptr.exists() else None
    if current != sid:
        pointer_dir.mkdir(parents=True, exist_ok=True)
        ptr.write_text(sid)


def resolve(mode: str) -> tuple:
    """
    Resolve the current owrap session, minting one in start mode.
    """
    env_sid = os.environ.get("SESSION_ID", "").strip()
    ccsid = os.environ.get("CLAUDE_CODE_SESSION_ID", "").strip()
    cid = os.environ.get("CODEX_SESSION_ID", "").strip()

    if env_sid:
        sf = session_file(env_sid)
        if sf.exists():
            # Keep the ccsid/codex anchor from going stale behind SESSION_ID.
            if ccsid:
                _rebind_stale_anchor(env_sid, ccsid, BY_CCSID_DIR, ccsid_pointer)
            if cid:
                _rebind_stale_anchor(
                    env_sid, cid, BY_CODEX_SESSION_ID_DIR, codex_session_id_pointer,
                )
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

    if cid:
        ptr = codex_session_id_pointer(cid)
        if ptr.exists():
            sid = ptr.read_text().strip()
            sf = session_file(sid)
            if sf.exists():
                return sid, sf, "codex_session_id"
            ptr.unlink(missing_ok=True)

    if mode == "start":
        sid = mint_session_id()
        sf = session_file(sid)
        data = {
            "session_id": sid,
            "claude_session_id": ccsid,
            "opencode_run_id": oid,
            "codex_session_id": cid,
            "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        _write(sf, data)
        if ccsid:
            BY_CCSID_DIR.mkdir(parents=True, exist_ok=True)
            ccsid_pointer(ccsid).write_text(sid)
        if oid:
            BY_OPENCODE_RUN_ID_DIR.mkdir(parents=True, exist_ok=True)
            opencode_run_id_pointer(oid).write_text(sid)
        if cid:
            BY_CODEX_SESSION_ID_DIR.mkdir(parents=True, exist_ok=True)
            codex_session_id_pointer(cid).write_text(sid)
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
    Bind target_sid to an environment anchor.

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


def all_attached_codex_session_id_pairs() -> list:
    """
    Return (codex_session_id, owrap_sid) for every currently-attached
    Codex window, across every owrap session.
    """
    if not BY_CODEX_SESSION_ID_DIR.exists():
        return []
    pairs = []
    for p in BY_CODEX_SESSION_ID_DIR.iterdir():
        if not p.is_file():
            continue
        sid = p.read_text().strip()
        if sid:
            pairs.append((p.name, sid))
    return pairs


def _suggest_attach_targets(token: str, sessions: list) -> list:
    """
    Return session/project/repository strings close to token, for a
    "did you mean" hint when no exact match was found.
    """

    candidates = set()
    for s in sessions:
        candidates.add(s.get("session_id", ""))
        candidates.add(s.get("project_id", ""))
        candidates.add(s.get("subproject_id", ""))
        candidates.add(s.get("repository_id", ""))
        if s.get("project_id") and s.get("subproject_id"):
            candidates.add(f"{s['project_id']}/{s['subproject_id']}")
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

    Tries an exact session id first, then an exact match on
    project_id/subproject_id/repository_id; hits are unioned and
    deduped by session_id.

    Returns (status, payload):
      ("session_id", token) — token is a valid session id
      ("unique", session_dict) — exactly one session matched
      ("ambiguous", (differential, [session_dicts])) — 2+ matched
      ("none", [suggestions]) — no match; near-miss strings, if any
    """
    if session_file(token).exists():
        return "session_id", token

    sessions = list_sessions()
    fields = ("project_id", "subproject_id", "repository_id")
    field_matches = [
        s for s in sessions if any(s.get(field) == token for field in fields)
    ]
    field_matches.extend(
        s for s in sessions
        if s.get("project_id") and s.get("subproject_id")
        and f"{s['project_id']}/{s['subproject_id']}" == token
    )

    seen = {}
    for s in field_matches:
        seen[s["session_id"]] = s
    matches = list(seen.values())

    if not matches:
        return "none", _suggest_attach_targets(token, sessions)
    if len(matches) == 1:
        return "unique", matches[0]

    varying = [
        field for field in (
            "project_id", "subproject_id", "repository_id",
        )
        if len({s.get(field, "") for s in matches}) > 1
    ]
    differential = varying[0] if len(varying) == 1 else "multi"

    matches.sort(key=lambda s: (
        s.get("project_id", ""), s.get("subproject_id", ""),
    ))
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
        if differential != "multi":
            label = s.get(differential, "-")
        else:
            label = (
                f"project={s.get('project_id', '-')} "
                f"subproject={s.get('subproject_id', '-')} "
                f"repository={s.get('repository_id', '-')}"
            )
        lines.append(f"  {label:<24} session={s['session_id']}")
    return "\n".join(lines)


def print_known_sessions():
    """
    Print the session id/identity table for all known sessions.
    """
    print("Known sessions:")
    for s in list_sessions():
        ccsid_val = s.get("claude_session_id", "-")
        _cc = ccsid_val[:8] if ccsid_val != "-" else "-"
        identity = ""
        if s.get("target_kind") == "project":
            identity = (
                f" project={s.get('project_id', '-')}"
                f"/{s.get('subproject_id') or 'main'}"
            )
        elif s.get("target_kind") == "repository":
            identity = f" repository={s.get('repository_id', '-')}"
        print(
            f"  {s['session_id']}  started={s.get('started', '-')}  "
            f"ccsid={_cc}{identity}",
        )


def resolve_session_or_exit(token: str, print_known_on_none: bool = False) -> str:
    """
    Resolve a user-typed session id/project/repository target to a session id,
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
    Bind a session to the caller's Claude, OpenCode, or Codex identity.
    """
    ccsid = os.environ.get("CLAUDE_CODE_SESSION_ID", "").strip()
    oid = os.environ.get("OPENCODE_RUN_ID", "").strip()
    cid = os.environ.get("CODEX_SESSION_ID", "").strip()
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
        _clear_anchor(target_sid, BY_CODEX_SESSION_ID_DIR)
        d["claude_session_id"] = ccsid
        d["opencode_run_id"] = ""
        d["codex_session_id"] = ""
    elif oid:
        prev_sid = _bind_anchor(
            target_sid, oid, BY_OPENCODE_RUN_ID_DIR,
            opencode_run_id_pointer(oid), "opencode_run_id",
        )
        _clear_anchor(target_sid, BY_CCSID_DIR)
        _clear_anchor(target_sid, BY_CODEX_SESSION_ID_DIR)
        d["opencode_run_id"] = oid
        d["claude_session_id"] = ""
        d["codex_session_id"] = ""
    elif cid:
        prev_sid = _bind_anchor(
            target_sid, cid, BY_CODEX_SESSION_ID_DIR,
            codex_session_id_pointer(cid), "codex_session_id",
        )
        _clear_anchor(target_sid, BY_CCSID_DIR)
        _clear_anchor(target_sid, BY_OPENCODE_RUN_ID_DIR)
        d["codex_session_id"] = cid
        d["claude_session_id"] = ""
        d["opencode_run_id"] = ""
    else:
        _clear_anchor(target_sid, BY_CCSID_DIR)
        _clear_anchor(target_sid, BY_OPENCODE_RUN_ID_DIR)
        _clear_anchor(target_sid, BY_CODEX_SESSION_ID_DIR)
        d["claude_session_id"] = ""
        d["opencode_run_id"] = ""
        d["codex_session_id"] = ""
        d["attached_ppid"] = str(os.getppid())

    d["last_attach"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    _write(sf, d)
    return target_sid, sf, prev_sid


def detach() -> str | None:
    """
    Release the caller's session pointer and return its owrap session ID.
    """
    ccsid = os.environ.get("CLAUDE_CODE_SESSION_ID", "").strip()
    oid = os.environ.get("OPENCODE_RUN_ID", "").strip()
    cid = os.environ.get("CODEX_SESSION_ID", "").strip()

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
    if not sid and cid:
        ptr = codex_session_id_pointer(cid)
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
        if cid and d.get("codex_session_id") == cid:
            d["codex_session_id"] = ""
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


def set_session_identity(
    session_id: str,
    *,
    project_id: str | None = None,
    subproject_id: str | None = None,
    repository_id: str | None = None,
    repositories: list[str] | None = None,
    branch_parent: str | None = None,
    branch_repository: str | None = None,
    branch_ref: str | None = None,
) -> None:
    """
    Store an explicit project or repository target on a session.
    """
    if bool(project_id) == bool(repository_id):
        raise ValueError("choose exactly one project or repository target")
    if repository_id and (
        subproject_id or branch_parent or branch_repository or branch_ref
    ):
        raise ValueError("repository-only sessions cannot have a subproject")
    if subproject_id and not project_id:
        raise ValueError("subproject requires a project")
    if branch_parent and not subproject_id:
        raise ValueError("branch parent requires a subproject")
    if branch_parent and branch_parent == subproject_id:
        raise ValueError("branch subproject cannot be its own parent")
    if bool(branch_parent) != bool(branch_repository) or (
        bool(branch_parent) != bool(branch_ref)
    ):
        raise ValueError("branch requires parent, repository, and ref")

    repo_ids = list(dict.fromkeys(repositories or []))
    if repository_id:
        if repo_ids and repo_ids != [repository_id]:
            raise ValueError(
                "repository-only session must target its sole repository"
            )
        repo_ids = [repository_id]
    if branch_repository and branch_repository not in repo_ids:
        raise ValueError("branch repository must be associated with the session")

    sf = session_file(session_id)
    if not sf.exists():
        raise FileNotFoundError(f"session not found: {session_id}")
    data = _parse(sf)
    data.update({
        "target_kind": "project" if project_id else "repository",
        "project_id": project_id or "",
        "subproject_id": subproject_id or "",
        "repository_id": repository_id or "",
        "repositories": json.dumps(repo_ids, separators=(",", ":")),
        "branch_parent": branch_parent or "",
        "branch_repository": branch_repository or "",
        "branch_ref": branch_ref or "",
    })
    _write(sf, data)


def remove_session(session_id: str):
    """
    Delete a session file and all pointers to it.
    """
    sf = session_file(session_id)
    if sf.exists():
        sf.unlink(missing_ok=True)
    for pointer_dir in (
        BY_CCSID_DIR, BY_OPENCODE_RUN_ID_DIR, BY_CODEX_SESSION_ID_DIR,
    ):
        if pointer_dir.exists():
            for ptr in pointer_dir.iterdir():
                if ptr.is_file() and ptr.read_text().strip() == session_id:
                    ptr.unlink(missing_ok=True)
