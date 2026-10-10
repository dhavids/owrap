import json
import shutil
import time
from pathlib import Path

from . import Record
from .identity import (
    attached_session_ids, rename_backup_dir, resolve_project_id,
    resolve_repository_id, resolve_root, update_sessions,
)
from ...actions.run.attach import Attach
from ...actions.run.detach import Detach
from ...utils.memory.records import (
    _dump_yaml, _record, _slug, _write_atomic, add_repository, session_repositories,
)


def _rename_repository(old_id: str, new_id: str, workspace: str = "") -> None:
    """
    Rename a repository directory, its record, every project's link
    to it, every repository-only session's `repository_id`, and
    every project session's `repositories` list entry.
    """
    root = resolve_root(workspace)
    old_id = resolve_repository_id(root, old_id)
    new_id = _slug_new_repository(new_id)
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
    _relink_repository(root, old_id, new_id)
    rename_backup_dir(f"repository/{old_id}", f"repository/{new_id}")
    update_sessions(
        lambda d: d.get("repository_id") == old_id,
        lambda d: d.update(repository_id=new_id),
    )
    update_sessions(
        lambda d: old_id in session_repositories(d),
        lambda d: d.update(repositories=json.dumps(
            [new_id if r == old_id else r for r in session_repositories(d)],
            separators=(",", ":"),
        )),
    )


def _slug_new_repository(new_id: str) -> str:
    from ...utils.memory.records import _slug
    return _slug(new_id, "repository")


def _relink_repository(root: Path, old_id: str, new_id: str) -> None:
    projects_dir = root / "projects"
    if not projects_dir.is_dir():
        return
    for yaml_path in projects_dir.glob("*/*.yaml"):
        project_id = yaml_path.stem
        try:
            record = _record(yaml_path, "project", project_id)
        except (FileNotFoundError, ValueError):
            continue
        if _relink_one_record(record, old_id, new_id):
            record["last_updated"] = time.time()
            _write_atomic(yaml_path, _dump_yaml(record))


def _relink_one_record(record: dict, old_id: str, new_id: str) -> bool:
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
            entry["repositories"] = [new_id if r == old_id else r for r in sub_repos]
            changed = True
        if entry.get("branch_repository") == old_id:
            entry["branch_repository"] = new_id
            changed = True
    return changed


def _remove_repository(repo_id: str, workspace: str = "") -> None:
    """
    Delete a repository's directory entirely. Refuses if any project
    still links it, or if any session still targets it.
    """
    root = resolve_root(workspace)
    repo_id = resolve_repository_id(root, repo_id)
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
    attached = attached_session_ids(
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


def _link_repository(repo_id: str, project_id: str, workspace: str = "") -> None:
    """
    Append `repo_id` to a project's `repositories:` list, if not
    already there.
    """
    root = resolve_root(workspace)
    repo_id = resolve_repository_id(root, repo_id)
    if not (root / "repositories" / repo_id).is_dir():
        raise FileNotFoundError(f"repository not found: {repo_id}")
    project_id = resolve_project_id(root, project_id)
    directory = root / "projects" / project_id
    yaml_path = directory / f"{project_id}.yaml"
    if not directory.is_dir():
        raise FileNotFoundError(f"project not found: {project_id}")
    record = _record(yaml_path, "project", project_id)
    repositories = record.setdefault("repositories", [])
    if repo_id not in repositories:
        repositories.append(repo_id)
        record["last_updated"] = time.time()
        _write_atomic(yaml_path, _dump_yaml(record))


def _unlink_repository(repo_id: str, project_id: str, workspace: str = "") -> None:
    """
    Remove `repo_id` from a project's `repositories:` list, if
    present.
    """
    root = resolve_root(workspace)
    repo_id = resolve_repository_id(root, repo_id)
    project_id = resolve_project_id(root, project_id)
    directory = root / "projects" / project_id
    yaml_path = directory / f"{project_id}.yaml"
    if not directory.is_dir():
        raise FileNotFoundError(f"project not found: {project_id}")
    record = _record(yaml_path, "project", project_id)
    repositories = record.get("repositories", [])
    if repo_id in repositories:
        repositories.remove(repo_id)
        record["last_updated"] = time.time()
        _write_atomic(yaml_path, _dump_yaml(record))


class Repository(Record, Attach, Detach):
    """
    A repository record: its own directory and `<id>.yaml` under
    `docs_root/repositories/`. `add`/`update`/`remove` manage the
    record itself; `attach`/`detach` link or unlink it from a
    project.
    """

    kind = "repository"

    usage = {
        "add": {
            "usage": "<repo_id> [checkout]",
            "args": [
                ("repo_id", "the repository's id"),
                ("checkout", "optional checkout path to record"),
            ],
            "examples": ["myrepo"],
        },
        "update": {
            "usage": "<old_id> <new_id>",
            "args": [("old_id", "current id"), ("new_id", "new id")],
            "examples": ["myrepo renamed-repo"],
        },
        "remove": {
            "usage": "<repo_id>",
            "args": [("repo_id", "repository to delete")],
            "examples": ["myrepo"],
        },
        "attach": {
            "usage": "<repo_id> <project_id>",
            "args": [("repo_id", "repository to link"), ("project_id", "target project")],
            "examples": ["myrepo myproject"],
        },
        "detach": {
            "usage": "<repo_id> <project_id>",
            "args": [
                ("repo_id", "repository to unlink"), ("project_id", "target project"),
            ],
            "examples": ["myrepo myproject"],
        },
    }

    messages = {
        "add": "Added repository {repo_id}",
        "update": "Renamed repository {old_id} -> {new_id}",
        "remove": "Removed repository {repo_id}",
        "attach": "ATTACHED repo={repo_id} project={project_id}",
        "detach": "DETACHED repo={repo_id} project={project_id}",
    }


    # Public Methods

    def add(self, repo_id: str = None, checkout: str = None) -> None:
        if repo_id is None:
            self._usage("add")
        self._edit(add_repository, repo_id, checkout, self._workspace())
        self._ok("add", repo_id=repo_id)

    def update(self, old_id: str = None, new_id: str = None) -> None:
        if new_id is None:
            self._usage("update")
        self._edit(_rename_repository, old_id, new_id, self._workspace())
        self._ok("update", old_id=old_id, new_id=new_id)

    def remove(self, repo_id: str = None) -> None:
        if repo_id is None:
            self._usage("remove")
        self._edit(_remove_repository, repo_id, self._workspace())
        self._ok("remove", repo_id=repo_id)


    # Private Methods

    def _on_attach(self, repo_id: str = None, project_id: str = None) -> dict:
        if repo_id is None or project_id is None:
            self._usage("attach")
        self._edit(_link_repository, repo_id, project_id, self._workspace())
        return {"repo_id": repo_id, "project_id": project_id}

    def _on_detach(self, repo_id: str = None, project_id: str = None) -> dict:
        if repo_id is None or project_id is None:
            self._usage("detach")
        self._edit(_unlink_repository, repo_id, project_id, self._workspace())
        return {"repo_id": repo_id, "project_id": project_id}
