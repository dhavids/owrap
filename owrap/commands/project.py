import difflib
import json
import os
import tempfile
from pathlib import Path

from ..utils.filelock import file_lock
from ..utils.memory.records import (
    _record, _slug, _subproject_stub_text, docs_root, resolve_memory_target,
)
from ..utils.session.resolver import (
    _parse, resolve, set_session_identity,
)


def _write_atomic(path: Path, content: str) -> None:
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(content)
        if path.exists():
            os.chmod(name, path.stat().st_mode)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def _yaml_text(record: dict) -> str:
    try:
        import yaml
    except ImportError as exc:
        raise ValueError("PyYAML is required to edit project records") from exc
    return yaml.safe_dump(record, sort_keys=False, allow_unicode=True)


class ProjectRunner:
    """
    Select and create project scopes for the current session.
    """

    def main(self) -> None:
        """
        Select the current session's main project record.
        """
        session_id, data = self._project_session()
        self._select(session_id, data, "")
        print(f"Project: {data['project_id']}/main")

    def sub(self, name: str, force: bool = False) -> None:
        """
        Select an existing subproject or create a regular subproject.
        """
        name = _slug(name, "subproject")
        session_id, data = self._project_session()
        project_id = data["project_id"]
        directory = docs_root(data.get("workspace", "")) / "projects" / project_id
        yaml_path = directory / f"{project_id}.yaml"
        markdown_path = directory / f"{name}.md"
        created = False

        with file_lock(yaml_path.with_suffix(".yaml.lock")):
            record = _record(yaml_path, "project", project_id)
            subprojects = record.get("subprojects")
            if not isinstance(subprojects, dict):
                raise ValueError("project subprojects must be a mapping")
            entry = subprojects.get(name)
            if isinstance(entry, dict):
                if entry.get("archived"):
                    raise ValueError(f"archived subproject: {project_id}/{name}")
            elif entry is not None:
                raise ValueError(f"invalid subproject: {project_id}/{name}")
            else:
                suggestions = self._suggest(name, subprojects)
                if suggestions and not force:
                    options = ", ".join(f"'{item}'" for item in suggestions)
                    raise ValueError(
                        f"unknown subproject '{name}'. Did you mean {options}? "
                        f"Use 'owrap sub {suggestions[0]}', or pass -f to "
                        f"create '{name}'"
                    )
                if markdown_path.exists():
                    raise FileExistsError(
                        f"subproject file already exists: {markdown_path}"
                    )
                subprojects[name] = {
                    "kind": "regular", "file": markdown_path.name,
                    "parent": "main",
                }
                before_yaml = yaml_path.read_text()
                try:
                    with markdown_path.open("x") as handle:
                        created = True
                        handle.write(_subproject_stub_text(project_id, name))
                    _write_atomic(yaml_path, _yaml_text(record))
                except Exception:
                    _write_atomic(yaml_path, before_yaml)
                    if created:
                        markdown_path.unlink(missing_ok=True)
                    raise

        self._select(session_id, data, name)
        action = "Created and selected" if created else "Subproject"
        print(f"{action}: {project_id}/{name}")

    def subs(self) -> None:
        """
        List the current project session's subprojects.
        """
        _, data = self._project_session()
        project_id = data["project_id"]
        directory = docs_root(data.get("workspace", "")) / "projects" / project_id
        record = _record(
            directory / f"{project_id}.yaml", "project", project_id,
        )
        subprojects = record.get("subprojects")
        if not isinstance(subprojects, dict):
            raise ValueError("project subprojects must be a mapping")
        if not subprojects:
            print(f"No subprojects for {project_id}.")
            return
        current = data.get("subproject_id", "")
        print(f"Subprojects for {project_id}:")
        for name, entry in subprojects.items():
            marker = "*" if name == current else " "
            archived = (
                " [archived]" if isinstance(entry, dict)
                and entry.get("archived") else ""
            )
            print(f"{marker} {name}{archived}")

    def _project_session(self) -> tuple[str, dict]:
        session_id, path, _ = resolve(mode="refresh")
        if not session_id or path is None or not path.is_file():
            raise ValueError("no active session; start or attach a session first")
        data = _parse(path)
        if data.get("target_kind") != "project" or not data.get("project_id"):
            raise ValueError("the active session does not target a project")
        return session_id, data

    def _select(
        self, session_id: str, data: dict, subproject_id: str,
    ) -> None:
        candidate = {**data, "subproject_id": subproject_id}
        target = resolve_memory_target(candidate)
        set_session_identity(
            session_id,
            project_id=target.project_id,
            subproject_id=target.subproject_id,
            repositories=list(target.repository_ids),
            branch_parent=target.branch_parent or None,
            branch_repository=target.branch_repository or None,
            branch_ref=target.branch_ref or None,
        )

    @staticmethod
    def _suggest(name: str, subprojects: dict) -> list[str]:
        active = [
            item for item, entry in subprojects.items()
            if isinstance(entry, dict) and not entry.get("archived")
        ]
        return difflib.get_close_matches(name, active, n=3, cutoff=0.7)
