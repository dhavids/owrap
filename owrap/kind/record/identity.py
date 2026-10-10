"""
Project/subproject/repository identity-resolution helpers shared by
every `Record`-shaped kind and `Project`.
"""
import os
from pathlib import Path

from ...session.resolver import (
    _parse, _write, list_sessions, session_file, session_files,
)
from ...utils.memory.records import _slug, docs_root
from ...utils.paths import BACKUPS_DIR


def current_workspace() -> str:
    """
    The workspace name recorded on the attached session, or "" if
    there is no attached session or it has none set.
    """
    sid = os.environ.get("SESSION_ID", "").strip()
    if not sid:
        return ""
    sf = session_file(sid)
    if not sf.exists():
        return ""
    return _parse(sf).get("workspace", "")


def resolve_root(workspace: str = "") -> Path:
    """
    The docs root for `workspace`, or for the attached session's own
    workspace if `workspace` is empty.
    """
    return docs_root(workspace or current_workspace())


def resolve_identity(root: Path, kind: str, field: str, token: str) -> str:
    """
    Resolve a rename/remove target to an exact id: a literal
    directory match wins outright, otherwise a session id is matched
    against every session's `field`, refusing if those sessions
    disagree on the id.
    """
    if (root / kind / token).is_dir():
        return token
    matches = set()
    for session in list_sessions():
        hit = token in (session.get("session_id"), session.get(field))
        value = session.get(field)
        if hit and value:
            matches.add(value)
    if not matches:
        raise FileNotFoundError(f"no {kind.rstrip('s')} matches '{token}'")
    if len(matches) > 1:
        raise ValueError(
            f"'{token}' matches more than one {kind.rstrip('s')} "
            f"({', '.join(sorted(matches))}) — use the exact id"
        )
    return next(iter(matches))


def resolve_project_id(root: Path, token: str) -> str:
    """
    Resolve `token` to an exact, slugified project id.
    """
    return _slug(resolve_identity(root, "projects", "project_id", token), "project")


def resolve_repository_id(root: Path, token: str) -> str:
    """
    Resolve `token` to an exact, slugified repository id.
    """
    return _slug(
        resolve_identity(root, "repositories", "repository_id", token), "repository",
    )


def rename_backup_dir(old_label: str, new_label: str) -> None:
    """
    Move a backup directory from its old `project/<id>[/<subproject_
    id>]` or `repository/<id>` key to the new one. No-op if there's
    nothing to move, or if something already exists at the new key.
    """
    old_dir = BACKUPS_DIR / old_label
    new_dir = BACKUPS_DIR / new_label
    if old_dir.is_dir() and not new_dir.exists():
        new_dir.parent.mkdir(parents=True, exist_ok=True)
        old_dir.rename(new_dir)


def update_sessions(matches, mutate) -> int:
    """
    Mutate every session file `matches` selects, via `mutate`,
    returning how many were changed.
    """
    count = 0
    for sf in session_files():
        data = _parse(sf)
        if not matches(data):
            continue
        mutate(data)
        _write(sf, data)
        count += 1
    return count


def attached_session_ids(matches) -> list:
    """
    Every session id whose own file `matches` selects.
    """
    return [s["session_id"] for s in list_sessions() if matches(s)]
