import os
import tempfile
from contextlib import ExitStack
from datetime import date
from pathlib import Path

from owrap.utils.filelock import file_lock
from owrap.utils.memory.goals import read_goals
from owrap.utils.memory.records import (
    _markdown_path, _record, _slug, docs_root, resolve_memory_target,
)
from owrap.utils.parser.sections import extract_section, replace_section


def _write_atomic(path: Path, content: str):
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


def _body(text: str, heading: str) -> str:
    section = extract_section(text, heading)
    return "\n".join(section.splitlines()[1:]).strip() if section else ""


def _append(text: str, heading: str, addition: str) -> str:
    if not addition:
        return text
    section = extract_section(text, heading)
    block = section.rstrip() if section else heading
    return replace_section(text, heading, block + "\n\n" + addition)


def _decision_key(line: str) -> str:
    return line.removeprefix("- ").strip().casefold()


def _merge_document(parent: str, branch: str, branch_id: str, goals: list):
    existing_goals = {
        text.strip().casefold() for _, text in goals["parent"]
    }
    pending = [
        text for done, text in goals["branch"]
        if not done and text.strip().casefold() not in existing_goals
    ]
    parent = _append(
        parent, "## Goals", "\n".join(f"- [ ] {item}" for item in pending),
    )

    findings = _body(branch, "## Findings")
    if findings:
        findings = "\n".join(
            "#" + line if line.startswith("### ") else line
            for line in findings.splitlines()
        )
        parent = _append(
            parent, "## Findings", f"### From {branch_id}\n\n{findings}",
        )

    parent_decisions = {
        _decision_key(line) for line in _body(parent, "## Decisions").splitlines()
        if line.startswith("- ")
    }
    decisions = [
        line for line in _body(branch, "## Decisions").splitlines()
        if line.startswith("- ") and _decision_key(line) not in parent_decisions
    ]
    parent = _append(parent, "## Decisions", "\n".join(decisions))
    return parent, pending, findings, decisions


class BranchRunner:
    """
    Create and reconcile project branch records without changing Git branches.
    """

    def create(
        self, project_id: str, branch_id: str, parent_id: str,
        repository_id: str, branch_ref: str, workspace: str = "",
    ) -> Path:
        """
        Create a branch subproject record linked to an existing parent.
        """
        project_id = _slug(project_id, "project")
        branch_id = _slug(branch_id, "subproject")
        if parent_id != "main":
            _slug(parent_id, "parent")
        repository_id = _slug(repository_id, "repository")
        if (
            not branch_ref or branch_ref != branch_ref.strip()
            or any(char.isspace() for char in branch_ref)
            or ".." in branch_ref or "@{" in branch_ref
        ):
            raise ValueError("invalid branch ref")
        root = docs_root(workspace)
        directory = root / "projects" / project_id
        yaml_path = directory / f"{project_id}.yaml"
        branch_path = directory / f"{branch_id}.md"
        with file_lock(yaml_path.with_suffix(".yaml.lock")):
            record = _record(yaml_path, "project", project_id)
            subprojects = record.get("subprojects")
            if not isinstance(subprojects, dict):
                raise ValueError("project subprojects must be a mapping")
            if branch_id in subprojects or branch_path.exists():
                raise ValueError(f"subproject already exists: {branch_id}")
            parent = resolve_memory_target({
                "target_kind": "project", "project_id": project_id,
                "subproject_id": "" if parent_id == "main" else parent_id,
                "workspace": workspace,
            })
            if repository_id not in parent.repository_ids:
                raise ValueError(
                    f"repository {repository_id} is not linked to {parent_id}"
                )
            parent_file = parent.project_path.name
            content = (
                f"# {branch_id}\n\n## Overview\n\n"
                f"Branch of [{parent_id}]({parent_file}) for `{branch_ref}`.\n\n"
                "## Goals\n\n## Status\n\nBranch open.\n\n"
                "## Decisions\n\n## Findings\n\n## Notes\n"
            )
            subprojects[branch_id] = {
                "kind": "branch", "file": branch_path.name,
                "parent": parent_id, "branch_repository": repository_id,
                "branch_ref": branch_ref,
            }
            created = False
            try:
                with branch_path.open("x") as handle:
                    created = True
                    handle.write(content)
                _write_atomic(yaml_path, _yaml_text(record))
            except Exception:
                if created:
                    branch_path.unlink(missing_ok=True)
                raise
        return branch_path

    def merge(
        self, project_id: str, branch_id: str, apply: bool = False,
        workspace: str = "",
    ) -> dict:
        """
        Preview or apply a documentation merge and archive the branch record.
        """
        project_id = _slug(project_id, "project")
        branch_id = _slug(branch_id, "subproject")
        root = docs_root(workspace)
        directory = root / "projects" / project_id
        yaml_path = directory / f"{project_id}.yaml"
        archive_path = directory / f"{branch_id}.archived.md"
        with file_lock(yaml_path.with_suffix(".yaml.lock")):
            record = _record(yaml_path, "project", project_id)
            entry = record.get("subprojects", {}).get(branch_id)
            if not isinstance(entry, dict) or entry.get("kind") != "branch":
                raise ValueError(f"branch subproject not found: {branch_id}")
            if entry.get("archived"):
                raise ValueError(f"branch already archived: {branch_id}")
            parent_id = entry.get("parent", "")
            parent = resolve_memory_target({
                "target_kind": "project", "project_id": project_id,
                "subproject_id": "" if parent_id == "main" else parent_id,
                "workspace": workspace,
            })
            branch_path = _markdown_path(directory, entry.get("file", ""))
            parent_path = parent.project_path
            if not branch_path.is_file() or not parent_path.is_file():
                raise FileNotFoundError("branch or parent Markdown record is missing")
            if archive_path.exists():
                raise FileExistsError(f"archive already exists: {archive_path}")
            locks = sorted((branch_path, parent_path), key=str)
            with ExitStack() as stack:
                for path in locks:
                    stack.enter_context(file_lock(path.with_suffix(".md.lock")))
                branch_text = branch_path.read_text()
                parent_text = parent_path.read_text()
                goals = {
                    "parent": read_goals(parent_path),
                    "branch": read_goals(branch_path),
                }
                merged, pending, findings, decisions = _merge_document(
                    parent_text, branch_text, branch_id, goals,
                )
                preview = {
                    "branch": branch_path, "parent": parent_path,
                    "archive": archive_path, "goals": pending,
                    "findings": findings, "decisions": decisions,
                    "applied": False,
                }
                if not apply:
                    return preview
                entry["archived"] = True
                entry["file"] = archive_path.name
                entry["merged_into"] = parent_id
                entry["merged_at"] = date.today().isoformat()
                archived = _append(
                    branch_text, "## Archive",
                    f"Merged into [{parent_id}]({parent_path.name}) on "
                    f"{entry['merged_at']}. Documentation only; Git was "
                    "not changed.",
                )
                before_yaml = yaml_path.read_text()
                created = False
                try:
                    with archive_path.open("x") as handle:
                        created = True
                        handle.write(archived)
                    _write_atomic(parent_path, merged)
                    _write_atomic(yaml_path, _yaml_text(record))
                    branch_path.unlink()
                except Exception:
                    _write_atomic(parent_path, parent_text)
                    _write_atomic(yaml_path, before_yaml)
                    if created:
                        archive_path.unlink(missing_ok=True)
                    raise
                preview["applied"] = True
                return preview

    def run(self, action: str, **kwargs):
        """
        Execute a branch command and print its result.
        """
        if action == "create":
            path = self.create(**kwargs)
            print(f"Created branch record: {path}")
            print("Git branch unchanged.")
            return
        if action != "merge":
            raise ValueError(f"unknown branch action: {action}")
        result = self.merge(**kwargs)
        print(f"Branch: {result['branch']}")
        print(f"Parent: {result['parent']}")
        print(f"Open goals to copy: {len(result['goals'])}")
        for goal in result["goals"]:
            print(f"  - {goal}")
        print(f"Findings to copy: {bool(result['findings'])}")
        if result["findings"]:
            print(result["findings"])
        print(f"Decisions to copy: {len(result['decisions'])}")
        for decision in result["decisions"]:
            print(f"  {decision}")
        print(f"Archive: {result['archive']}")
        print("Documentation merge applied." if result["applied"] else
              "Preview only. Pass --apply after review.")
        print("Git branch unchanged.")
