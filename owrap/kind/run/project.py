import difflib
import time
from pathlib import Path

from .session import Session
from ..record.identity import (
    current_workspace, rename_backup_dir, resolve_identity, update_sessions,
)
from ...utils.io.filelock import file_lock
from ...utils.memory.records import (
    _dump_yaml, _record, _slug, _subproject_stub_text, _write_atomic,
    docs_root, resolve_memory_target,
)
from ...utils.parser.sections import extract_section
from ...session.resolver import _parse, resolve, set_session_identity


def _rewrite_project_backrefs(project_dir: Path, old_id: str, new_id: str) -> None:
    old_ref = f"[{old_id}](main.md)"
    new_ref = f"[{new_id}](main.md)"
    for md_path in project_dir.glob("*.md"):
        text = md_path.read_text()
        if old_ref in text:
            md_path.write_text(text.replace(old_ref, new_ref))


def _rename_project(old_id: str, new_id: str, workspace: str = "") -> None:
    """
    Rename a project directory, its record, every subproject's
    back-reference, and every session's `project_id`.
    """
    root = docs_root(workspace or current_workspace())
    old_id = _slug(resolve_identity(root, "projects", "project_id", old_id), "project")
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
    _rewrite_project_backrefs(new_dir, old_id, new_id)
    rename_backup_dir(f"project/{old_id}", f"project/{new_id}")
    update_sessions(
        lambda d: d.get("project_id") == old_id,
        lambda d: d.update(project_id=new_id),
    )


def _project_session() -> tuple:
    """
    Resolve the attached session's project record -- fails if nothing
    is attached, or the attached session has no project target.
    """
    session_id, path, _ = resolve(mode="refresh")
    if not session_id or path is None or not path.is_file():
        raise ValueError("no active session; start or attach a session first")
    data = _parse(path)
    if data.get("target_kind") != "project" or not data.get("project_id"):
        raise ValueError("the active session does not target a project")
    return session_id, data


def _set_target_risk(value: str) -> dict:
    """
    Set the risk level on the active session's project, or its
    currently selected subproject.
    """
    _, data = _project_session()
    project_id = data["project_id"]
    subproject_id = data.get("subproject_id", "")
    directory = docs_root(data.get("workspace", "")) / "projects" / project_id
    yaml_path = directory / f"{project_id}.yaml"
    with file_lock(yaml_path.with_suffix(".yaml.lock")):
        record = _record(yaml_path, "project", project_id)
        if subproject_id:
            subprojects = record.get("subprojects", {})
            entry = subprojects.get(subproject_id)
            if not isinstance(entry, dict):
                raise ValueError(f"unknown subproject: {project_id}/{subproject_id}")
            entry["risk"] = value
        else:
            record["risk"] = value
        record["last_updated"] = time.time()
        _write_atomic(yaml_path, _dump_yaml(record))
    return {"project_id": project_id, "name": subproject_id or "main"}


def _select_subproject(session_id: str, data: dict, subproject_id: str) -> None:
    """
    Point the attached session at `subproject_id` (or main, if
    empty) -- fails if it doesn't exist or is archived.
    """
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


def _suggest_subprojects(name: str, subprojects: dict) -> list:
    active = [
        item for item, entry in subprojects.items()
        if isinstance(entry, dict) and not entry.get("archived")
    ]
    return difflib.get_close_matches(name, active, n=3, cutoff=0.7)


def _create_or_select_subproject(name: str, force: bool = False) -> bool:
    """
    Select an existing subproject or create a regular one, then point
    the attached session at it. Returns True if it was created.
    """
    name = _slug(name, "subproject")
    session_id, data = _project_session()
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
            suggestions = _suggest_subprojects(name, subprojects)
            if suggestions and not force:
                options = ", ".join(f"'{item}'" for item in suggestions)
                raise ValueError(
                    f"unknown subproject '{name}'. Did you mean {options}? "
                    f"Use 'owrap project set {suggestions[0]}', or pass "
                    f"'force' to create '{name}'"
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
                _write_atomic(yaml_path, _dump_yaml(record))
            except Exception:
                _write_atomic(yaml_path, before_yaml)
                if created:
                    markdown_path.unlink(missing_ok=True)
                raise

    _select_subproject(session_id, data, name)
    return created


def _print_subprojects() -> None:
    """
    List the attached session's project's subprojects.
    """
    _, data = _project_session()
    project_id = data["project_id"]
    directory = docs_root(data.get("workspace", "")) / "projects" / project_id
    record = _record(directory / f"{project_id}.yaml", "project", project_id)
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


class Project(Session):
    """
    A project: a session target with its own identity on top of
    `Session`'s lifecycle -- rename, subproject add/set/get.
    """

    kind = "project"

    usage = {
        "start": {
            "usage": "[<id>]",
            "args": [("id", "project id to start or attach to")],
            "examples": ["myproject"],
            "purpose": "Start a targeted project session",
            "group": "session",
        },
        "update": {
            "usage": "<old-id> <new-id>",
            "args": [
                ("old-id", "the project's current id"),
                ("new-id", "the new id to rename it to"),
            ],
            "examples": ["myproject renamed-project"],
        },
        "add": {
            "usage": "<name> [force]",
            "args": [
                ("name", "subproject to create, or select if it "
                         "already exists"),
                ("force", "reserved keyword -- skip the typo-suggestion "
                          "check and create anyway"),
            ],
            "examples": ["docs", "experimental force"],
            "purpose": "Select or create a regular subproject",
            "group": "session",
        },
        "set": {
            "usage": "[<name>|risk <low|high>]",
            "args": [
                ("name", "existing subproject to select; omit to "
                         "select main"),
                ("risk", "set the active target's (project, or its "
                         "selected subproject) risk level"),
            ],
            "examples": ["", "docs", "risk high", "risk low"],
            "purpose": "Return the current project session to main, "
                   "select an existing subproject, or set its risk level",
            "group": "session",
        },
        "get": {
            "usage": "[main|subs|sub <name>|name|path|risk]",
            "args": [
                ("main", "the project's own Goals/Decisions (default)"),
                ("subs", "list the project's subprojects"),
                ("sub", "a named subproject's Goals/Decisions"),
                ("name", "report the active project/subproject id"),
                ("path", "report the active record's file path"),
                ("risk", "report the active target's risk level"),
            ],
            "examples": ["", "main", "subs", "sub docs", "name", "path", "risk"],
            "purpose": "Read project/subproject goals and decisions, or "
                   "report identity",
            "group": "record",
        },
    }

    messages = {
        "update": "Renamed project {old_id} -> {new_id}",
        "add": "{action}: {project_id}/{name}",
        "set": "Selected: {project_id}/{name}",
        "risk": "{project_id}/{name}: risk set to {value}",
        "name": "{name}",
        "path": "{path}",
    }


    # Public Methods

    def update(self, old_id: str, new_id: str = None) -> None:
        """
        Rename a project: its directory, record, every subproject's
        back-reference, and every session's `project_id`. Overrides
        the base `Update` mixin directly -- it operates on a project
        id pair, not a resolved target + edit payload.
        """
        if new_id is None:
            self._usage("update")
        self._edit(_rename_project, old_id, new_id, current_workspace())
        self._ok("update", old_id=old_id, new_id=new_id)

    def add(self, name: str = None, force: str = None) -> None:
        """
        Create (or select, if it already exists) a subproject of
        the active session's project.
        """
        if not name:
            self._usage("add")
        created = self._edit(_create_or_select_subproject, name, force=force == "force")
        action = "Created and selected" if created else "Subproject"
        _, data = _project_session()
        self._ok("add", action=action, project_id=data["project_id"], name=name)

    def set(self, name: str = None, value: str = None) -> None:
        """
        Select an existing subproject (or main, if `name` is
        omitted) without creating one -- fails if it doesn't exist.
        `set risk <low|high>` instead sets the active target's risk
        level.
        """
        if name == "risk":
            if value not in ("low", "high"):
                self._usage("set")
            result = self._edit(_set_target_risk, value)
            self._ok("risk", **result, value=value)
            return
        session_id, data = self._edit(_project_session)
        self._edit(_select_subproject, session_id, data, name or "")
        self._ok("set", project_id=data["project_id"], name=name or "main")

    def get(self, facet: str = None, name: str = None) -> None:
        """
        Report a project/subproject fact selected by `facet` (see `usage`).
        """
        self._report(facet, name)


    # Private Methods

    def _default_get(self) -> None:
        """
        `owrap project get` with no args reports the project's own
        Goals/Decisions, same as the explicit `main` facet.
        """
        self._report(None, None)

    def _report(self, facet: str = None, name: str = None) -> None:
        _, data = self._edit(_project_session)
        facet = facet or "main"
        if facet in ("main", "sub"):
            if facet == "sub" and not name:
                self._usage("get")
            self._print_content(data, name or "")
        elif facet == "subs":
            _print_subprojects()
        elif facet == "name":
            subproject = data.get("subproject_id") or "main"
            self._ok("name", name=f"{data['project_id']}/{subproject}")
        elif facet == "path":
            self._ok("path", path=resolve_memory_target(data).project_path)
        elif facet == "risk":
            risk = "high" if resolve_memory_target(data).high_risk else "low"
            self._ok("name", name=risk)
        else:
            self._usage("get")

    def _print_content(self, data: dict, subproject_id: str) -> None:
        """
        Print a project or subproject record's Goals and Decisions
        sections.
        """
        target = resolve_memory_target({**data, "subproject_id": subproject_id})
        text = target.project_path.read_text()
        sections = [
            section for heading in ("## Goals", "## Decisions")
            if (section := extract_section(text, heading))
        ]
        if not sections:
            print(f"No Goals/Decisions found in {target.project_path}")
            return
        print("\n\n".join(sections))
