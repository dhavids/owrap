import time

from . import Record
from .identity import (
    attached_session_ids, rename_backup_dir, resolve_project_id, resolve_root,
    update_sessions,
)
from ...utils.memory.records import _dump_yaml, _record, _slug, _write_atomic


def _rename_subproject(
    project_id: str, old_sub: str, new_sub: str, workspace: str = "",
) -> None:
    """
    Rename a subproject's entry in its project record, every sibling
    subproject's `parent` reference to it, and every session's
    `subproject_id`.
    """
    root = resolve_root(workspace)
    project_id = resolve_project_id(root, project_id)
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
                raise FileExistsError(f"subproject file already exists: {new_md_path}")
            old_md_path.rename(new_md_path)
            entry["file"] = new_md_path.name
    subprojects[new_sub] = entry
    for other in subprojects.values():
        if isinstance(other, dict) and other.get("parent") == old_sub:
            other["parent"] = new_sub
    record["last_updated"] = time.time()
    _write_atomic(yaml_path, _dump_yaml(record))
    rename_backup_dir(
        f"project/{project_id}/{old_sub}", f"project/{project_id}/{new_sub}",
    )
    update_sessions(
        lambda d: (
            d.get("project_id") == project_id and d.get("subproject_id") == old_sub
        ),
        lambda d: d.update(subproject_id=new_sub),
    )


def _remove_subproject(project_id: str, sub_id: str, workspace: str = "") -> None:
    """
    Delete a subproject's yaml entry and markdown file. Refuses if
    any session still targets it.
    """
    root = resolve_root(workspace)
    project_id = resolve_project_id(root, project_id)
    sub_id = _slug(sub_id, "subproject")
    directory = root / "projects" / project_id
    yaml_path = directory / f"{project_id}.yaml"
    record = _record(yaml_path, "project", project_id)
    subprojects = record.get("subprojects", {})
    if sub_id not in subprojects:
        raise ValueError(f"unknown subproject: {project_id}/{sub_id}")
    attached = attached_session_ids(
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


class Subproject(Record):
    """
    A subproject's own identity: its entry in its project's
    `subprojects:` yaml map, plus its markdown file. Renames or
    deletes the identity record itself, independent of any session --
    creating or selecting one is `Project.add`/`Project.set`.
    """

    kind = "subproject"

    usage = {
        "update": {
            "usage": "<project_id> <old_id> <new_id>",
            "args": [
                ("project_id", "the owning project"),
                ("old_id", "current subproject id"), ("new_id", "new id"),
            ],
            "examples": ["myproject docs renamed-docs"],
        },
        "remove": {
            "usage": "<project_id> <sub_id>",
            "args": [
                ("project_id", "the owning project"),
                ("sub_id", "subproject to delete"),
            ],
            "examples": ["myproject docs"],
        },
    }

    messages = {
        "update": "Renamed subproject {project_id}/{old_id} -> {new_id}",
        "remove": "Removed subproject {project_id}/{sub_id}",
    }


    # Public Methods

    def update(
        self, project_id: str = None, old_id: str = None, new_id: str = None,
    ) -> None:
        if new_id is None:
            self._usage("update")
        self._edit(_rename_subproject, project_id, old_id, new_id, self._workspace())
        self._ok("update", project_id=project_id, old_id=old_id, new_id=new_id)

    def remove(self, project_id: str = None, sub_id: str = None) -> None:
        if sub_id is None:
            self._usage("remove")
        self._edit(_remove_subproject, project_id, sub_id, self._workspace())
        self._ok("remove", project_id=project_id, sub_id=sub_id)
