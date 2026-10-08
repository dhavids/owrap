import os
import time
from pathlib import Path

from ..utils.memory.records import _record, _slug, _write_atomic, _dump_yaml, docs_root
from ..utils.session.resolver import (
    _parse, _write, list_sessions, session_file, session_files,
)


def _current_workspace() -> str:
    sid = os.environ.get("SESSION_ID", "").strip()
    if not sid:
        return ""
    sf = session_file(sid)
    if not sf.exists():
        return ""
    return _parse(sf).get("workspace", "")


def _resolve_identity(root: Path, kind: str, field: str, token: str) -> str:
    """
    Resolve a rename target to an exact id: a literal directory match
    wins outright (always unambiguous), otherwise a session id is
    matched against every session's `field`, refusing if those
    sessions disagree on the id.
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


class RenameRunner:
    """
    Rename a project, subproject, or repository identity, updating every
    session file and cross-reference that points at the old id.
    """

    def project(self, old_id: str, new_id: str, workspace: str = "") -> None:
        """
        Rename a project directory, its record, every subproject's
        back-reference, and every session's `project_id`.
        """
        root = docs_root(workspace or _current_workspace())
        old_id = _slug(
            _resolve_identity(root, "projects", "project_id", old_id), "project",
        )
        new_id = _slug(new_id, "project")
        old_dir = root / "projects" / old_id
        new_dir = root / "projects" / new_id
        if not old_dir.is_dir():
            raise FileNotFoundError(f"project not found: {old_id}")
        if new_dir.exists():
            raise FileExistsError(f"project already exists: {new_id}")
        record = _record(old_dir / f"{old_id}.yaml", "project", old_id)
        old_dir.rename(new_dir)
        (new_dir / f"{old_id}.yaml").rename(new_dir / f"{new_id}.yaml")
        record["id"] = new_id
        record["last_updated"] = time.time()
        _write_atomic(new_dir / f"{new_id}.yaml", _dump_yaml(record))
        self._rewrite_project_backrefs(new_dir, old_id, new_id)
        self._update_sessions(
            lambda d: d.get("project_id") == old_id,
            lambda d: d.update(project_id=new_id),
        )

    def subproject(
        self, project_id: str, old_sub: str, new_sub: str, workspace: str = "",
    ) -> None:
        """
        Rename a subproject's entry in its project record, every sibling
        subproject's `parent` reference to it, and every session's
        `subproject_id`.
        """
        root = docs_root(workspace or _current_workspace())
        project_id = _slug(
            _resolve_identity(root, "projects", "project_id", project_id), "project",
        )
        old_sub = _slug(old_sub, "subproject")
        new_sub = _slug(new_sub, "subproject")
        directory = root / "projects" / project_id
        yaml_path = directory / f"{project_id}.yaml"
        record = _record(yaml_path, "project", project_id)
        subprojects = record.get("subprojects", {})
        if old_sub not in subprojects:
            raise ValueError(f"unknown subproject: {project_id}/{old_sub}")
        if new_sub in subprojects:
            raise FileExistsError(f"subproject already exists: {project_id}/{new_sub}")
        entry = subprojects.pop(old_sub)
        if isinstance(entry, dict):
            old_md_path = directory / entry.get("file", f"{old_sub}.md")
            new_md_path = directory / f"{new_sub}.md"
            if old_md_path.exists() and old_md_path != new_md_path:
                if new_md_path.exists():
                    raise FileExistsError(
                        f"subproject file already exists: {new_md_path}"
                    )
                old_md_path.rename(new_md_path)
                entry["file"] = new_md_path.name
        subprojects[new_sub] = entry
        for other in subprojects.values():
            if isinstance(other, dict) and other.get("parent") == old_sub:
                other["parent"] = new_sub
        record["last_updated"] = time.time()
        _write_atomic(yaml_path, _dump_yaml(record))
        self._update_sessions(
            lambda d: (
                d.get("project_id") == project_id
                and d.get("subproject_id") == old_sub
            ),
            lambda d: d.update(subproject_id=new_sub),
        )

    def repository(self, old_id: str, new_id: str, workspace: str = "") -> None:
        """
        Rename a repository directory, its record, every project's link
        to it, and every session's `repository_id`.
        """
        root = docs_root(workspace or _current_workspace())
        old_id = _slug(
            _resolve_identity(root, "repositories", "repository_id", old_id),
            "repository",
        )
        new_id = _slug(new_id, "repository")
        old_dir = root / "repositories" / old_id
        new_dir = root / "repositories" / new_id
        if not old_dir.is_dir():
            raise FileNotFoundError(f"repository not found: {old_id}")
        if new_dir.exists():
            raise FileExistsError(f"repository already exists: {new_id}")
        record = _record(old_dir / f"{old_id}.yaml", "repository", old_id)
        old_dir.rename(new_dir)
        (new_dir / f"{old_id}.yaml").rename(new_dir / f"{new_id}.yaml")
        record["id"] = new_id
        record["last_updated"] = time.time()
        _write_atomic(new_dir / f"{new_id}.yaml", _dump_yaml(record))
        self._relink_repository(root, old_id, new_id)
        self._update_sessions(
            lambda d: d.get("repository_id") == old_id,
            lambda d: d.update(repository_id=new_id),
        )


    # Private Methods

    def _rewrite_project_backrefs(
        self, project_dir: Path, old_id: str, new_id: str,
    ) -> None:
        old_ref = f"[{old_id}](main.md)"
        new_ref = f"[{new_id}](main.md)"
        for md_path in project_dir.glob("*.md"):
            text = md_path.read_text()
            if old_ref in text:
                md_path.write_text(text.replace(old_ref, new_ref))

    def _relink_repository(self, root: Path, old_id: str, new_id: str) -> None:
        projects_dir = root / "projects"
        if not projects_dir.is_dir():
            return
        for yaml_path in projects_dir.glob("*/*.yaml"):
            project_id = yaml_path.stem
            try:
                record = _record(yaml_path, "project", project_id)
            except (FileNotFoundError, ValueError):
                continue
            changed = self._relink_one_record(record, old_id, new_id)
            if changed:
                record["last_updated"] = time.time()
                _write_atomic(yaml_path, _dump_yaml(record))

    def _relink_one_record(self, record: dict, old_id: str, new_id: str) -> bool:
        changed = False
        repos = record.get("repositories", [])
        if old_id in repos:
            record["repositories"] = [new_id if r == old_id else r for r in repos]
            changed = True
        for entry in record.get("subprojects", {}).values():
            if not isinstance(entry, dict):
                continue
            sub_repos = entry.get("repositories", [])
            if old_id in sub_repos:
                entry["repositories"] = [
                    new_id if r == old_id else r for r in sub_repos
                ]
                changed = True
            if entry.get("branch_repository") == old_id:
                entry["branch_repository"] = new_id
                changed = True
        return changed

    def _update_sessions(self, matches, mutate) -> int:
        count = 0
        for sf in session_files():
            data = _parse(sf)
            if not matches(data):
                continue
            mutate(data)
            _write(sf, data)
            count += 1
        return count
