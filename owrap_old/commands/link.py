import time

from .rename import _current_workspace, _resolve_identity
from owrap.utils.filelock import file_lock
from owrap.utils.memory.records import _dump_yaml, _record, _slug, _write_atomic, docs_root


def link_project_repository(repo_id: str, project_id: str, workspace: str = "") -> None:
    """
    Link a repository to a project: append repo_id to the project's
    `repositories:` list, if not already there.
    """
    root = docs_root(workspace or _current_workspace())
    repo_id = _slug(
        _resolve_identity(root, "repositories", "repository_id", repo_id),
        "repository",
    )
    if not (root / "repositories" / repo_id).is_dir():
        raise FileNotFoundError(f"repository not found: {repo_id}")
    project_id = _slug(
        _resolve_identity(root, "projects", "project_id", project_id), "project",
    )
    directory = root / "projects" / project_id
    yaml_path = directory / f"{project_id}.yaml"
    if not directory.is_dir():
        raise FileNotFoundError(f"project not found: {project_id}")
    with file_lock(yaml_path.with_suffix(".yaml.lock")):
        record = _record(yaml_path, "project", project_id)
        repositories = record.setdefault("repositories", [])
        if repo_id not in repositories:
            repositories.append(repo_id)
            record["last_updated"] = time.time()
            _write_atomic(yaml_path, _dump_yaml(record))


def unlink_project_repository(repo_id: str, project_id: str, workspace: str = "") -> None:
    """
    Unlink a repository from a project: remove repo_id from the
    project's `repositories:` list, if present.
    """
    root = docs_root(workspace or _current_workspace())
    repo_id = _slug(
        _resolve_identity(root, "repositories", "repository_id", repo_id),
        "repository",
    )
    project_id = _slug(
        _resolve_identity(root, "projects", "project_id", project_id), "project",
    )
    directory = root / "projects" / project_id
    yaml_path = directory / f"{project_id}.yaml"
    if not directory.is_dir():
        raise FileNotFoundError(f"project not found: {project_id}")
    with file_lock(yaml_path.with_suffix(".yaml.lock")):
        record = _record(yaml_path, "project", project_id)
        repositories = record.get("repositories", [])
        if repo_id in repositories:
            repositories.remove(repo_id)
            record["last_updated"] = time.time()
            _write_atomic(yaml_path, _dump_yaml(record))
