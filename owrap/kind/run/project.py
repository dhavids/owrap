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
from ...utils.memory.names import check_new_name, find_target
from ...utils.parser.sections import doc_outline, extract_section
from ...utils.parser.text import preview_lines
from ...utils.session.resolver import _parse, resolve, set_session_identity


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
    check_new_name(workspace or current_workspace(), new_id, "project")
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
            check_new_name(data.get("workspace", ""), name, "subproject")
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


def _scratch_label(data: dict) -> str:
    return f"{data['project_id']}/{data.get('subproject_id') or 'main'}"


def _scratch_path(data: dict) -> Path:
    """
    The active target's scratch-notes path, by convention -- never
    stored in the project record. Raises if the target itself
    (project or subproject) doesn't resolve.
    """
    target = resolve_memory_target(data)
    directory = target.project_path.parent
    name = (
        f"{target.subproject_id}.scratch.md" if target.subproject_id
        else "scratch.md"
    )
    return directory / name


def _create_scratch(path: Path) -> bool:
    """
    Create an empty scratch-notes file at `path` if it doesn't
    already exist. Returns True if created.
    """
    try:
        with path.open("x"):
            pass
        return True
    except FileExistsError:
        return False


def _clear_scratch(path: Path) -> bool:
    """
    Delete the scratch-notes file at `path` if it exists. Returns
    True if it was removed.
    """
    if not path.is_file():
        return False
    path.unlink()
    return True


def _print_subprojects(data: dict) -> None:
    """
    List a project's subprojects, marking the session's current one.
    """
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
                ("name", "subproject to create, or select if it already "
                         "exists -- 'scratch' creates the active target's "
                         "scratch notes file instead"),
                ("force", "reserved keyword -- skip the typo-suggestion "
                          "check and create anyway"),
            ],
            "examples": ["docs", "experimental force", "scratch"],
            "purpose": "Select or create a regular subproject, or create "
                   "scratch notes",
            "group": "session",
        },
        "clear": {
            "usage": "scratch",
            "args": [
                ("scratch", "delete the active target's scratch notes"),
            ],
            "examples": ["scratch"],
            "purpose": "Delete the active target's disposable scratch "
                   "notes",
            "group": "record",
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
            "usage": "[<name>] [doc [<section> [<subsection>]] | subs | "
                     "scratch [path] | name | path | risk]",
            "args": [
                ("(none)", "path, Goals and Decisions of the active target "
                           "(the subproject, if the session is on one)"),
                ("<name>", "a project or subproject by name, read-only; if "
                         "ambiguous, use project/sub (project/main for "
                         "the project's own record)"),
                ("doc", "the record's sections: with no section, an "
                        "outline; else that section, or one of its "
                        "subsections (number or part of a title)"),
                ("subs", "list the project's subprojects"),
                ("scratch", "scratch notes, or their file path with 'path'"),
                ("name", "report the project/subproject id"),
                ("path", "report the record's file path"),
                ("risk", "report the risk level"),
            ],
            "examples": [
                "", "doc", "doc notes", "doc notes 2", "doc notes tune",
                "subs", "scratch", "scratch path", "name", "path", "risk",
                "owrap", "owrap doc notes", "gen/wcp", "wcp/main path",
            ],
            "short_usage": "[<name>] [doc [<section> [<subsection>]]|name]",
            "purpose": "Read a project/subproject's path, goals, decisions "
                   "and sections",
            "group": "record",
        },
    }

    messages = {
        "update": "Renamed project {old_id} -> {new_id}",
        "add": "{verb}: {project_id}/{name}",
        "scratch_add": "{verb} scratch notes: {label}",
        "set": "Selected: {project_id}/{name}",
        "risk": "{project_id}/{name}: risk set to {value}",
        "name": "{name}",
        "path": "{path}",
        "get": "{text}",
        "clear": "Cleared scratch notes: {label}",
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
        the active session's project -- or, for `name == "scratch"`,
        create the active target's scratch notes file instead.
        """
        if not name:
            self._usage("add")
        if name == "scratch":
            _, data = self._edit(_project_session)
            path = self._edit(_scratch_path, data)
            created = self._edit(_create_scratch, path)
            verb = "Created" if created else "Already exists:"
            self._ok("scratch_add", verb=verb, label=_scratch_label(data))
            return
        created = self._edit(_create_or_select_subproject, name, force=force == "force")
        verb = "Created and selected" if created else "Subproject"
        _, data = _project_session()
        self._ok("add", verb=verb, project_id=data["project_id"], name=name)

    def clear(self, facet: str = None) -> None:
        """
        Delete the active target's scratch notes -- disposable
        design/dev notes that are never part of the durable project
        or subproject record.
        """
        if facet != "scratch":
            self._usage("clear")
        _, data = self._edit(_project_session)
        path = self._edit(_scratch_path, data)
        removed = self._edit(_clear_scratch, path)
        label = _scratch_label(data)
        if removed:
            self._ok("clear", label=label)
        else:
            print(f"No scratch notes for {label} to clear.")

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

    def get(self, *args) -> None:
        """
        Report a project/subproject fact or section selected by `args`
        (see `usage`).
        """
        self._report(list(args))


    # Private Methods

    def _default_get(self) -> None:
        """
        `owrap project get` with no args reports the active target's
        Goals/Decisions.
        """
        self._report([])

    def _report(self, args: list) -> None:
        """
        Read a record: the session's own target by default, or any
        project/subproject named first. Reads only -- never writes.
        """
        args = list(args)
        facets = self.facets()
        named = bool(args) and args[0] not in facets
        if named:
            data = self._edit(self._named_target, args.pop(0))
        else:
            _, data = self._edit(_project_session)
        if not args:
            self._facet_goals(data, named)
        elif args[0] in facets:
            getattr(self, f"_facet_{args[0]}")(data, args[1:])
        else:
            self._usage("get")

    def _facet_goals(self, data: dict, named: bool) -> None:
        """
        No facet: path, Goals and Decisions of the target.
        """
        subproject = data.get("subproject_id") or ""
        self._print_content(data, subproject)
        if subproject and not named:
            print(
                f"\nproject-level: owrap get project {data['project_id']}/main"
            )

    def _facet_doc(self, data: dict, rest: list) -> None:
        self._doc(data, data.get("subproject_id") or "", rest)

    def _facet_subs(self, data: dict, rest: list) -> None:
        _print_subprojects(data)

    def _facet_scratch(self, data: dict, rest: list) -> None:
        path = self._edit(_scratch_path, data)
        if rest[:1] == ["path"]:
            self._ok("path", path=str(path))
        elif not path.is_file():
            print(
                f"No scratch notes for {_scratch_label(data)} yet -- "
                f"create with 'owrap add project scratch'."
            )
        else:
            self._ok(
                "get", text=f"{path}\n\n{preview_lines(path.read_text())}",
            )

    def _facet_name(self, data: dict, rest: list) -> None:
        self._ok("name", name=_scratch_label(data))

    def _facet_path(self, data: dict, rest: list) -> None:
        self._ok("path", path=resolve_memory_target(data).project_path)

    def _facet_risk(self, data: dict, rest: list) -> None:
        risk = "high" if resolve_memory_target(data).high_risk else "low"
        self._ok("name", name=risk)

    def _named_target(self, token: str) -> dict:
        """
        Session-shaped data for a project/subproject named by `token`,
        resolved without needing an attached session.
        """
        workspace = current_workspace()
        project_id, subproject_id = find_target(workspace, token)
        return {
            "target_kind": "project", "project_id": project_id,
            "subproject_id": subproject_id, "workspace": workspace,
        }

    def _doc(self, data: dict, subproject: str, selectors: list) -> None:
        """
        Print the record's outline, one `##` section, or one `###`
        subsection of it. A selector that matches nothing fails with
        what does exist.
        """
        target = self._edit(
            resolve_memory_target, {**data, "subproject_id": subproject},
        )
        sections = doc_outline(target.project_path.read_text())
        label = f"{target.project_path.name}"
        if not selectors:
            lines = [f"{target.project_path}"]
            for number, section in enumerate(sections, 1):
                lines.append(f"{number:>3}  {section['title']}")
                for sub_number, sub in enumerate(section["subs"], 1):
                    lines.append(f"       {sub_number}. {sub['title']}")
            print("\n".join(lines))
            return
        section = self._pick(sections, selectors[0], "section", label)
        if len(selectors) == 1:
            print(section["block"])
            return
        sub = self._pick(
            section["subs"], selectors[1],
            "subsection", f"'{section['title']}'",
        )
        print(sub["block"])

    def _pick(self, items: list, selector: str, noun: str, where: str) -> dict:
        """
        One item by 1-based number (0 first, -1 last) or title
        (exact, else a unique case-insensitive substring); fails
        listing what exists.
        """
        titles = [item["title"] for item in items]
        if not items:
            self._fail(f"{where} has no {noun}s; ask without one for its content")
        listing = "; ".join(f"{n}. {t}" for n, t in enumerate(titles, 1))
        try:
            number = int(selector)
        except ValueError:
            number = None
        if number is not None:
            index = {0: 0, -1: len(items) - 1}.get(number, number - 1)
            if 0 <= index < len(items):
                return items[index]
            self._fail(f"no {noun} {selector} in {where}. Exists: {listing}")
        lowered = selector.lower()
        exact = [i for i, t in enumerate(titles) if t.lower() == lowered]
        found = exact or [
            i for i, t in enumerate(titles) if lowered in t.lower()
        ]
        if len(found) == 1:
            return items[found[0]]
        if not found:
            self._fail(f"no {noun} '{selector}' in {where}. Exists: {listing}")
        matches = "; ".join(f"{i + 1}. {titles[i]}" for i in found)
        self._fail(f"'{selector}' matches several {noun}s in {where}: {matches}")

    def _print_content(self, data: dict, subproject_id: str) -> None:
        """
        Print a project or subproject record's Goals and Decisions
        sections.
        """
        target = self._edit(
            resolve_memory_target, {**data, "subproject_id": subproject_id},
        )
        text = target.project_path.read_text()
        sections = [
            section for heading in ("## Goals", "## Decisions")
            if (section := extract_section(text, heading))
        ]
        print(target.project_path)
        if not sections:
            print("No Goals/Decisions found")
            return
        print("\n" + "\n\n".join(sections))


    # Class Methods

    @classmethod
    def facets(cls) -> tuple:
        """
        Return the keywords `get` reads after a name, one per
        `_facet_*` method.
        """
        return tuple(
            name[len("_facet_"):] for name in dir(cls)
            if name.startswith("_facet_") and name != "_facet_goals"
        )
