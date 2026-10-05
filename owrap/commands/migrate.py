import json
import re
import shutil
import subprocess
from pathlib import Path

import yaml

from ..utils.memory.records import docs_root
from ..utils.paths import OWRAP_HOME
from ..utils.session.resolver import _parse, _write

_META_SECTIONS = {
    "artifact map", "checkout and session rules", "environment setup",
    "mpe learner", "overview", "structure", "workflow",
}


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    if not slug:
        raise ValueError(f"cannot migrate empty identity from {value!r}")
    return slug


def _sections(text: str) -> tuple[str, dict[str, list[str]]]:
    preamble = []
    sections: dict[str, list[str]] = {}
    current = ""
    for line in text.splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            sections.setdefault(current, [])
        elif current:
            sections[current].append(line)
        else:
            preamble.append(line)
    return "\n".join(preamble).strip(), sections


def _source(path: Path) -> tuple[str, dict[str, list[str]]]:
    if not path.is_file():
        return "", {}
    return _sections(path.read_text())


def _body(sections: dict[str, list[str]], name: str) -> str:
    for heading, lines in sections.items():
        if heading.casefold() == name.casefold():
            return "\n".join(lines).strip()
    return ""


def _goals(text: str) -> list[str]:
    return [
        line for line in text.splitlines()
        if line.lstrip().startswith(("- [ ]", "- [x]", "- [X]"))
    ]


def _record_text(title: str, goals: list[str], notes: list[str]) -> str:
    goal_text = "\n".join(dict.fromkeys(goals))
    note_text = "\n\n".join(value for value in notes if value.strip())
    return (
        f"# {title}\n\n## Goals\n\n{goal_text}\n\n"
        f"## Status\n\nMigrated from the legacy records.\n\n"
        f"## Decisions\n\n## Notes\n\n{note_text}\n"
    )


def _write_once(path: Path, content: str) -> None:
    if path.exists():
        if path.read_text() != content:
            raise FileExistsError(f"migration destination differs: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _copy_once(source: Path, destination: Path) -> None:
    if not source.is_file():
        return
    _write_once(destination, source.read_text())


def _merge_tree(source: Path, destination: Path) -> None:
    if not source.exists():
        return
    destination.mkdir(parents=True, exist_ok=True)
    for path in source.rglob("*"):
        target = destination / path.relative_to(source)
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif target.exists():
            if path.read_bytes() != target.read_bytes():
                raise FileExistsError(f"session artifact differs: {target}")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    shutil.rmtree(source)


class MigrateRunner:
    """
    Convert legacy session and record layouts to the current schema.
    """

    def run(
        self, home: str | None = None, record_root: str | None = None,
        mapping: str | None = None, apply: bool = False,
    ) -> dict:
        """
        Preview or apply the migration for one owrap home and docs root.
        """
        home_path = Path(home).expanduser().resolve() if home else OWRAP_HOME
        root = (
            Path(record_root).expanduser().resolve()
            if record_root else docs_root()
        )
        map_path = Path(mapping).expanduser().resolve() if mapping else None
        plan = self._plan(home_path, root, map_path)
        self._print(plan, apply)
        if apply:
            self._apply(plan)
        return plan

    def _plan(
        self, home: Path, root: Path, mapping: Path | None = None,
    ) -> dict:
        session_files = sorted((home / "sessions").glob("*.session"))
        sessions = [_parse(path) for path in session_files]
        project_ids = {
            data.get("research", "") for data in sessions
            if data.get("research")
        }
        for directory in ("projects", "memory", "todo"):
            project_ids.update(
                path.stem for path in (root / directory).glob("*.md")
            )
        project_map = {project_id: _slug(project_id) for project_id in project_ids}
        if len(set(project_map.values())) != len(project_map):
            raise ValueError("legacy project IDs collide after normalization")
        project_map = dict(sorted(project_map.items()))
        repositories, project_repositories = self._mapping(
            mapping, project_map,
        )
        return {
            "home": home,
            "root": root,
            "session_files": session_files,
            "sessions": sessions,
            "projects": project_map,
            "repositories": repositories,
            "project_repositories": project_repositories,
            "mapping": mapping,
        }

    def _mapping(
        self, path: Path | None, projects: dict[str, str],
    ) -> tuple[dict, dict[str, list[str]]]:
        if path is None:
            return {}, {}
        if not path.is_file():
            raise FileNotFoundError(f"migration map not found: {path}")
        data = yaml.safe_load(path.read_text()) or {}
        if not isinstance(data, dict):
            raise ValueError(f"invalid migration map: {path}")
        raw_repositories = data.get("repositories", {})
        raw_projects = data.get("projects", {})
        if not isinstance(raw_repositories, dict):
            raise ValueError("migration repositories must be a mapping")
        if not isinstance(raw_projects, dict):
            raise ValueError("migration projects must be a mapping")
        repositories = {}
        for raw_id, entry in raw_repositories.items():
            repo_id = _slug(str(raw_id))
            if repo_id != raw_id or not isinstance(entry, dict):
                raise ValueError(f"invalid repository mapping: {raw_id!r}")
            checkout = Path(str(entry.get("checkout", ""))).expanduser()
            if not checkout.is_absolute() or not checkout.is_dir():
                raise ValueError(f"invalid checkout for repository {repo_id}")
            checkout = checkout.resolve()
            result = subprocess.run(
                ["git", "-C", str(checkout), "rev-parse", "--show-toplevel"],
                check=False,
                capture_output=True,
                text=True,
            )
            if result.returncode or Path(result.stdout.strip()) != checkout:
                raise ValueError(
                    f"checkout must be a Git root for repository {repo_id}"
                )
            remote = entry.get("remote", "")
            if not isinstance(remote, str):
                raise ValueError(f"invalid remote for repository {repo_id}")
            repositories[repo_id] = {
                "checkout": str(checkout),
                "remote": remote,
            }
        known_projects = set(projects) | set(projects.values())
        links = {}
        for raw_id, repo_ids in raw_projects.items():
            if raw_id not in known_projects or not isinstance(repo_ids, list):
                raise ValueError(f"invalid project mapping: {raw_id!r}")
            project_id = projects.get(raw_id, raw_id)
            normalized = []
            for repo_id in repo_ids:
                if repo_id not in repositories:
                    raise ValueError(
                        f"unknown repository {repo_id!r} for project {raw_id}"
                    )
                if repo_id not in normalized:
                    normalized.append(repo_id)
            links[project_id] = normalized
        return repositories, links

    def _print(self, plan: dict, apply: bool) -> None:
        action = "Applying" if apply else "Preview"
        print(f"{action} legacy migration")
        print(f"  owrap home: {plan['home']}")
        print(f"  docs root:  {plan['root']}")
        print(f"  sessions:   {len(plan['sessions'])}")
        print(f"  projects:   {len(plan['projects'])}")
        print(f"  repositories: {len(plan['repositories'])}")
        for old_id, project_id in plan["projects"].items():
            if old_id != project_id:
                print(f"  rename:     {old_id} -> {project_id}")
        unresolved = sorted(
            project_id for project_id in plan["projects"].values()
            if project_id not in plan["project_repositories"]
        )
        if unresolved:
            print(f"  unmapped:   {', '.join(unresolved)}")
        if not apply:
            print("Preview only. Pass --apply after reviewing the paths above.")

    def _apply(self, plan: dict) -> None:
        self._migrate_repositories(plan)
        self._migrate_projects(plan)
        warnings = self._migrate_sessions(plan)
        self._migrate_configs(plan["home"])
        print("Migration applied.")
        for warning in warnings:
            print(f"Warning: {warning}")

    def _migrate_repositories(self, plan: dict) -> None:
        root = plan["root"]
        for repo_id, entry in plan["repositories"].items():
            directory = root / "repositories" / repo_id
            record = {
                "schema_version": 1,
                "kind": "repository",
                "id": repo_id,
                "main": "main.md",
                "checkout": entry["checkout"],
            }
            if entry["remote"]:
                record["remote"] = entry["remote"]
            _write_once(
                directory / f"{repo_id}.yaml",
                yaml.safe_dump(record, sort_keys=False),
            )
            _write_once(
                directory / "main.md",
                _record_text(repo_id, [], ["Migrated repository record."]),
            )

    def _migrate_projects(self, plan: dict) -> None:
        root = plan["root"]
        for old_id, project_id in plan["projects"].items():
            project_sessions = [
                data for data in plan["sessions"]
                if data.get("research") == old_id
            ]
            self._migrate_project(
                root, old_id, project_id, project_sessions, plan,
            )

    def _migrate_project(
        self, root: Path, old_id: str, project_id: str,
        sessions: list[dict], plan: dict,
    ) -> None:
        old_project = root / "projects" / f"{old_id}.md"
        old_memory = root / "memory" / f"{old_id}.md"
        old_todo = root / "todo" / f"{old_id}.md"
        project_pre, project_sections = _source(old_project)
        memory_pre, memory_sections = _source(old_memory)
        todo_pre, todo_sections = _source(old_todo)
        directory = root / "projects" / project_id
        legacy_subprojects = {
            data.get("area", "") for data in sessions
            if data.get("area") and data.get("area") != "main"
        }
        for source_sections in (
            project_sections, memory_sections, todo_sections,
        ):
            legacy_subprojects.update(
                heading for heading in source_sections
                if heading.casefold() not in _META_SECTIONS
                and heading.casefold() != "main"
            )
        subproject_map = {
            value: _slug(value) for value in legacy_subprojects if value
        }
        if len(set(subproject_map.values())) != len(subproject_map):
            raise ValueError(
                f"legacy subproject IDs collide for project {old_id}"
            )
        record = {
            "schema_version": 1,
            "kind": "project",
            "id": project_id,
            "main": "main.md",
            "repositories": plan["project_repositories"].get(
                project_id, [],
            ),
            "subprojects": {
                name: {
                    "kind": "regular", "file": f"{name}.md",
                    "parent": "main",
                }
                for name in sorted(subproject_map.values())
            },
        }
        yaml_text = yaml.safe_dump(record, sort_keys=False)
        _write_once(directory / f"{project_id}.yaml", yaml_text)
        main_notes = [
            project_pre, _body(project_sections, "Overview"),
            _body(project_sections, "main"), memory_pre,
            _body(memory_sections, "main"), todo_pre,
        ]
        main_goals = _goals(_body(todo_sections, "main"))
        _write_once(
            directory / "main.md",
            _record_text(project_id, main_goals, main_notes),
        )
        for old_name, name in sorted(subproject_map.items()):
            notes = [
                _body(project_sections, old_name),
                _body(memory_sections, old_name),
            ]
            goals = _goals(_body(todo_sections, old_name))
            _write_once(
                directory / f"{name}.md",
                _record_text(name, goals, notes),
            )
        _copy_once(old_project, directory / "legacy-project.md")
        _copy_once(old_memory, directory / "legacy-memory.md")
        _copy_once(old_todo, directory / "legacy-todo.md")

    def _migrate_sessions(self, plan: dict) -> list[str]:
        home = plan["home"]
        session_ids = {
            data.get("session_id", "") for data in plan["sessions"]
        }
        warnings = []
        for path, data in zip(plan["session_files"], plan["sessions"]):
            sid = data.get("session_id") or path.stem
            old_id = data.get("research", "")
            if old_id:
                project_id = plan["projects"][old_id]
                area = data.get("area", "main")
                repo_ids = plan["project_repositories"].get(project_id, [])
                data.update({
                    "target_kind": "project",
                    "project_id": project_id,
                    "subproject_id": (
                        "" if area == "main" else _slug(area)
                    ),
                    "repository_id": "",
                    "repositories": json.dumps(
                        repo_ids, separators=(",", ":"),
                    ),
                })
            parent = data.get("parent_session_id", "")
            if parent and parent not in session_ids:
                data["legacy_parent_session_id"] = parent
                data.pop("parent_session_id", None)
                warnings.append(
                    f"session {sid} referenced missing parent {parent}; "
                    "the old ID was retained as legacy_parent_session_id"
                )
            _write(path, data)
            _merge_tree(
                home / "docs" / "sessions" / sid,
                home / "sessions" / sid,
            )
        return warnings

    def _migrate_configs(self, home: Path) -> None:
        for path in sorted((home / "configs").glob("*.json")):
            data = json.loads(path.read_text())
            if "docs_root" not in data and data.get("research_root"):
                data["docs_root"] = data["research_root"]
            data.pop("research_root", None)
            path.write_text(json.dumps(data, indent=2) + "\n")
