import shutil
import time

from .rename import _current_workspace, _resolve_identity
from ..utils.memory.records import (
    _dump_yaml, _record, _slug, _write_atomic, docs_root, session_repositories,
)
from ..utils.session.resolver import list_sessions


def _attached_session_ids(matches) -> list[str]:
    return [s["session_id"] for s in list_sessions() if matches(s)]


def remove_project(old_id: str, workspace: str = "") -> None:
    """
    Delete a project's directory entirely. Refuses if it still has any
    non-archived subproject, or if any session still targets it.
    """
    root = docs_root(workspace or _current_workspace())
    old_id = _slug(
        _resolve_identity(root, "projects", "project_id", old_id), "project",
    )
    directory = root / "projects" / old_id
    if not directory.is_dir():
        raise FileNotFoundError(f"project not found: {old_id}")
    record = _record(directory / f"{old_id}.yaml", "project", old_id)
    active = [
        sub_id for sub_id, entry in record.get("subprojects", {}).items()
        if not (isinstance(entry, dict) and entry.get("archived"))
    ]
    if active:
        raise ValueError(
            f"project {old_id} still has subproject(s) "
            f"({', '.join(active)}) — remove them first"
        )
    attached = _attached_session_ids(lambda s: s.get("project_id") == old_id)
    if attached:
        raise ValueError(
            f"project {old_id} is still targeted by session(s) "
            f"({', '.join(attached)}) — detach them first"
        )
    shutil.rmtree(directory)


def remove_subproject(project_id: str, sub_id: str, workspace: str = "") -> None:
    """
    Delete a subproject's yaml entry and markdown file. Refuses if any
    session still targets it.
    """
    root = docs_root(workspace or _current_workspace())
    project_id = _slug(
        _resolve_identity(root, "projects", "project_id", project_id), "project",
    )
    sub_id = _slug(sub_id, "subproject")
    directory = root / "projects" / project_id
    yaml_path = directory / f"{project_id}.yaml"
    record = _record(yaml_path, "project", project_id)
    subprojects = record.get("subprojects", {})
    if sub_id not in subprojects:
        raise ValueError(f"unknown subproject: {project_id}/{sub_id}")
    attached = _attached_session_ids(
        lambda s: (
            s.get("project_id") == project_id and s.get("subproject_id") == sub_id
        ),
    )
    if attached:
        raise ValueError(
            f"subproject {project_id}/{sub_id} is still targeted by "
            f"session(s) ({', '.join(attached)}) — detach them first"
        )
    entry = subprojects.pop(sub_id)
    if isinstance(entry, dict):
        (directory / entry.get("file", f"{sub_id}.md")).unlink(missing_ok=True)
    record["last_updated"] = time.time()
    _write_atomic(yaml_path, _dump_yaml(record))


def remove_repository(repo_id: str, workspace: str = "") -> None:
    """
    Delete a repository's directory entirely. Refuses if any project
    still links it, or if any session still targets it.
    """
    root = docs_root(workspace or _current_workspace())
    repo_id = _slug(
        _resolve_identity(root, "repositories", "repository_id", repo_id),
        "repository",
    )
    directory = root / "repositories" / repo_id
    if not directory.is_dir():
        raise FileNotFoundError(f"repository not found: {repo_id}")
    linked = []
    projects_dir = root / "projects"
    if projects_dir.is_dir():
        for yaml_path in projects_dir.glob("*/*.yaml"):
            try:
                project_record = _record(yaml_path, "project", yaml_path.stem)
            except (FileNotFoundError, ValueError):
                continue
            if repo_id in project_record.get("repositories", []):
                linked.append(yaml_path.stem)
    if linked:
        raise ValueError(
            f"repository {repo_id} is still linked to project(s) "
            f"({', '.join(linked)}) — unlink them first"
        )
    attached = _attached_session_ids(
        lambda s: (
            s.get("repository_id") == repo_id or repo_id in session_repositories(s)
        ),
    )
    if attached:
        raise ValueError(
            f"repository {repo_id} is still targeted by session(s) "
            f"({', '.join(attached)}) — detach them first"
        )
    shutil.rmtree(directory)
