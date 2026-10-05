import json
import re
from dataclasses import dataclass
from pathlib import Path

from ..paths import _read_config, get_workspace_config

_SLUG = re.compile(r"[a-z0-9][a-z0-9-]*\Z")


@dataclass(frozen=True)
class MemoryTarget:
    """
    Paths and identity for one session's project or repository records.
    """

    kind: str
    project_id: str
    subproject_id: str
    project_path: Path | None
    repository_ids: tuple[str, ...]
    repository_paths: tuple[Path, ...]
    branch_parent: str = ""
    branch_repository: str = ""
    branch_ref: str = ""


def docs_root(workspace: str = "") -> Path:
    """
    Return the configured documentation root for a session workspace.
    """
    config = get_workspace_config(workspace) if workspace else {}
    base = _read_config()
    root = (
        config.get("docs_root") or config.get("research_root")
        or base.get("docs_root") or base.get("research_root")
    )
    if not root:
        raise ValueError("docs_root not configured")
    return Path(root)


def research_root(workspace: str = "") -> Path:
    """
    Return the documentation root for legacy callers.
    """
    return docs_root(workspace)


def _slug(value: str, label: str) -> str:
    if not isinstance(value, str) or not _SLUG.fullmatch(value):
        raise ValueError(f"invalid {label}: {value!r}")
    return value


def _record(
    path: Path, kind: str, identity: str, allow_missing: bool = False,
) -> dict:
    if not path.is_file():
        if allow_missing:
            return {"main": "main.md", "repositories": [], "subprojects": {}}
        raise FileNotFoundError(f"{kind} record not found: {path}")
    try:
        import yaml
    except ImportError as exc:
        raise ValueError("PyYAML is required to read project records") from exc
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid YAML record: {path}") from exc
    if not isinstance(data, dict) or data.get("kind") != kind:
        raise ValueError(f"invalid {kind} record: {path}")
    if data.get("id") != identity or data.get("schema_version") != 1:
        raise ValueError(f"invalid {kind} identity: {path}")
    return data


def _markdown_path(directory: Path, file_name: str) -> Path:
    if not isinstance(file_name, str):
        raise ValueError(f"invalid Markdown file: {file_name!r}")
    path = directory / file_name
    if path.parent != directory or path.suffix != ".md":
        raise ValueError(f"invalid Markdown file: {file_name!r}")
    return path


def resolve_memory_target(
    session: dict, allow_missing: bool = False,
    allow_archived: bool = False,
) -> MemoryTarget | None:
    """
    Resolve an explicit session identity to its Markdown records.
    """
    kind = session.get("target_kind", "")
    if kind not in ("project", "repository"):
        return None
    root = docs_root(session.get("workspace", ""))
    if kind == "repository":
        repo_id = _slug(session.get("repository_id", ""), "repository")
        directory = root / "repositories" / repo_id
        record = _record(
            directory / f"{repo_id}.yaml", "repository", repo_id,
            allow_missing,
        )
        path = _markdown_path(directory, record.get("main", "main.md"))
        return MemoryTarget(kind, "", "", None, (repo_id,), (path,))

    project_id = _slug(session.get("project_id", ""), "project")
    subproject_id = session.get("subproject_id", "")
    directory = root / "projects" / project_id
    record = _record(
        directory / f"{project_id}.yaml", "project", project_id,
        allow_missing,
    )
    file_name = record.get("main", "main.md")
    repos = record.get("repositories", [])
    entry = {}
    if allow_missing and not (directory / f"{project_id}.yaml").exists():
        repos = list(session_repositories(session))
    if subproject_id:
        _slug(subproject_id, "subproject")
        subprojects = record.get("subprojects", {})
        if not isinstance(subprojects, dict):
            raise ValueError(f"invalid subprojects for project {project_id}")
        entry = subprojects.get(subproject_id)
        if not isinstance(entry, dict):
            raise ValueError(f"unknown subproject: {project_id}/{subproject_id}")
        if entry.get("archived") and not allow_archived:
            raise ValueError(f"archived subproject: {project_id}/{subproject_id}")
        file_name = entry.get("file", f"{subproject_id}.md")
        node = entry
        seen = {subproject_id}
        while "repositories" not in node:
            parent = node.get("parent", "main")
            if parent == "main":
                node = record
                break
            if parent in seen or parent not in subprojects:
                raise ValueError(f"invalid parent for {project_id}/{subproject_id}")
            seen.add(parent)
            node = subprojects[parent]
            if not isinstance(node, dict):
                raise ValueError(f"invalid parent for {project_id}/{subproject_id}")
        repos = node.get("repositories", [])
    if not isinstance(repos, list):
        raise ValueError(f"invalid repositories for project {project_id}")
    repo_ids = tuple(dict.fromkeys(_slug(repo, "repository") for repo in repos))
    repo_paths = []
    for repo_id in repo_ids:
        repo_dir = root / "repositories" / repo_id
        repo = _record(
            repo_dir / f"{repo_id}.yaml", "repository", repo_id,
            allow_missing,
        )
        repo_paths.append(_markdown_path(repo_dir, repo.get("main", "main.md")))
    project_path = _markdown_path(directory, file_name)
    branch_parent = ""
    branch_repository = ""
    branch_ref = ""
    if entry.get("kind") == "branch":
        branch_parent = entry.get("parent", "")
        branch_repository = entry.get("branch_repository", "")
        branch_ref = entry.get("branch_ref", "")
        if (
            not branch_parent or branch_repository not in repo_ids
            or not branch_ref
        ):
            raise ValueError(f"invalid branch record: {project_id}/{subproject_id}")
    return MemoryTarget(
        kind, project_id, subproject_id, project_path,
        repo_ids, tuple(repo_paths), branch_parent,
        branch_repository, branch_ref,
    )


def session_repositories(session: dict) -> tuple[str, ...]:
    """
    Return the repository IDs stored on a session record.
    """
    try:
        values = json.loads(session.get("repositories", "[]"))
    except (TypeError, json.JSONDecodeError):
        return ()
    if not isinstance(values, list):
        return ()
    return tuple(value for value in values if isinstance(value, str))


def touched_repository_paths(
    target: MemoryTarget, paths: list[str], workspace: str,
) -> dict[str, Path]:
    """
    Return associated repository records whose checkout contains a touched path.
    """
    if not paths:
        return {}
    root = docs_root(workspace)
    selected = {}
    for repo_id, record_path in zip(
        target.repository_ids, target.repository_paths,
    ):
        directory = root / "repositories" / repo_id
        record = _record(directory / f"{repo_id}.yaml", "repository", repo_id)
        checkout_value = record.get("checkout", "")
        if not isinstance(checkout_value, str) or not checkout_value:
            continue
        checkout = Path(checkout_value)
        if not checkout.is_absolute() or not checkout.is_dir():
            continue
        checkout = checkout.resolve()
        for value in paths:
            source = Path(value)
            if source.is_absolute():
                candidates = [source]
            else:
                candidates = [Path(workspace) / source]
                if (
                    len(target.repository_ids) == 1
                    or (source.parts and source.parts[0] == checkout.name)
                    or (checkout / source).exists()
                ):
                    candidates.append(checkout / source)
            if any(
                candidate.resolve().is_relative_to(checkout)
                for candidate in candidates
            ):
                selected[repo_id] = record_path
                break
    return selected
