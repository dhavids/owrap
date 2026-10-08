import json
import os
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from ..filelock import file_lock
from ..parser.sections import extract_section, replace_section
from ..paths import _read_config, get_workspace_config

_SLUG = re.compile(r"[a-z0-9][a-z0-9-]*\Z")

IDENTITY_ALIASES = {"proj": "project", "sub": "subproject", "repo": "repository"}


def normalize_identity_kind(kind: str) -> str:
    """
    Map a short singular identity-kind alias (`proj`/`sub`/`repo`) to
    its canonical `project`/`subproject`/`repository` name.
    """
    return IDENTITY_ALIASES.get(kind, kind)


def count_bullets(path: Path, heading: str) -> int:
    """
    Count non-empty `- ` entries under `heading` in a Markdown file.
    Zero if the file or heading doesn't exist.
    """
    if not path.is_file():
        return 0
    section = extract_section(path.read_text(), heading)
    if not section:
        return 0
    return sum(
        1 for line in section.splitlines()[1:]
        if line.strip().startswith("- ")
    )


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
    root = config.get("docs_root") or base.get("docs_root")
    if not root:
        raise ValueError("docs_root not configured")
    return Path(root)


def _slug(value: str, label: str) -> str:
    if not isinstance(value, str) or not _SLUG.fullmatch(value):
        raise ValueError(
            f"invalid {label}: {value!r} — lowercase letters, digits, and "
            f"'-' only, starting with a letter or digit (no '_')"
        )
    return value


def _record(
    path: Path, kind: str, identity: str, allow_missing: bool = False,
) -> dict:
    if not path.is_file():
        if allow_missing:
            default_main = "memory.md" if kind == "repository" else "main.md"
            return {"main": default_main, "repositories": [], "subprojects": {}}
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
        path = _markdown_path(directory, record.get("main", "memory.md"))
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
        repo_paths.append(_markdown_path(repo_dir, repo.get("main", "memory.md")))
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


def _dump_yaml(record: dict) -> str:
    try:
        import yaml
    except ImportError as exc:
        raise ValueError("PyYAML is required to write repository records") from exc
    return yaml.safe_dump(record, sort_keys=False, allow_unicode=True)


def touch_record_last_updated(yaml_path: Path) -> float:
    """
    Bump a project/repository record's last_updated field to now, for any
    writer (Decisions, Goals, ctx dispatch, rename) that changes the
    record without already holding its own loaded copy to stamp inline.
    Returns the timestamp written, or the current time if the record
    couldn't be read (never raises).
    """
    now = time.time()
    with file_lock(yaml_path.with_suffix(".yaml.lock")):
        try:
            import yaml as _yaml
            record = _yaml.safe_load(yaml_path.read_text())
        except Exception:
            return now
        if not isinstance(record, dict):
            return now
        record["last_updated"] = now
        _write_atomic(yaml_path, _dump_yaml(record))
    return now


def _git_root(path: Path) -> Path | None:
    """
    Return the git repository root containing path, or None if there isn't
    one.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=path if path.is_dir() else path.parent,
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return Path(result.stdout.strip()).resolve()


def _git_remote(root: Path) -> str:
    """
    Return the origin remote URL for a git repo root, or "" if it has none.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def _repo_id_for_root(root: Path) -> str:
    """
    Derive a repository id slug from a git root's directory name.
    """
    slug = re.sub(r"[^a-z0-9-]+", "-", root.name.lower()).strip("-")
    return slug or "repo"


def _register_repository(root: Path, git_root: Path) -> str | None:
    """
    Create a repository record for git_root if one doesn't exist yet, or
    confirm an existing record already points at it. Returns its id, or
    None if an existing record with the same id points at a different
    checkout.
    """
    repo_id = _repo_id_for_root(git_root)
    directory = root / "repositories" / repo_id
    yaml_path = directory / f"{repo_id}.yaml"
    with file_lock(yaml_path.with_suffix(".yaml.lock")):
        if yaml_path.exists():
            record = _record(yaml_path, "repository", repo_id)
            checkout_value = record.get("checkout", "")
            if not checkout_value or Path(checkout_value).resolve() != git_root:
                return None
            return repo_id
        directory.mkdir(parents=True, exist_ok=True)
        record = {
            "schema_version": 1, "kind": "repository", "id": repo_id,
            "title": repo_id.replace("-", " ").title(),
            "main": "memory.md", "checkout": str(git_root),
        }
        remote = _git_remote(git_root)
        if remote:
            record["remote"] = remote
        record["last_updated"] = time.time()
        _write_atomic(yaml_path, _dump_yaml(record))
        _write_atomic(
            directory / "memory.md",
            f"# {repo_id}\n\n"
            "## Architecture\n\n\n"
            "## Components\n\n\n"
            "## Interfaces\n\n\n"
            "## Environment\n\n\n"
            "## Notes\n",
        )
    return repo_id


def _add_project_repository(root: Path, project_id: str, repo_id: str) -> None:
    """
    Append repo_id to a project's repositories list, if not already there.
    """
    directory = root / "projects" / project_id
    yaml_path = directory / f"{project_id}.yaml"
    with file_lock(yaml_path.with_suffix(".yaml.lock")):
        record = _record(yaml_path, "project", project_id)
        repositories = record.setdefault("repositories", [])
        if repo_id not in repositories:
            repositories.append(repo_id)
            record["last_updated"] = time.time()
            _write_atomic(yaml_path, _dump_yaml(record))


def _project_stub_text(project_id: str) -> str:
    return (
        f"# {project_id}\n\n"
        "## Overview\n\n\n"
        "## Goals\n\n\n"
        "## Status\n\n\n"
        "## Decisions\n\n\n"
        "## Notes\n"
    )


def _subproject_stub_text(project_id: str, subproject_id: str) -> str:
    title = subproject_id.replace("-", " ").title()
    return (
        f"# {title}\n\n"
        f"## Overview\n\nPart of [{project_id}](main.md).\n\n\n"
        "## Goals\n\n\n"
        "## Status\n\n\n"
        "## Decisions\n\n\n"
        "## Notes\n"
    )


def ensure_project_exists(
    workspace: str, project_id: str, subproject_id: str = "",
) -> None:
    """
    Create a project record, and a regular subproject within it if given,
    for whichever part doesn't already exist.
    """
    project_id = _slug(project_id, "project")
    root = docs_root(workspace)
    directory = root / "projects" / project_id
    yaml_path = directory / f"{project_id}.yaml"
    with file_lock(yaml_path.with_suffix(".yaml.lock")):
        if not yaml_path.exists():
            directory.mkdir(parents=True, exist_ok=True)
            record = {
                "schema_version": 1, "kind": "project", "id": project_id,
                "title": project_id, "main": "main.md",
                "repositories": [], "subprojects": {},
                "last_updated": time.time(),
            }
            _write_atomic(yaml_path, _dump_yaml(record))
            _write_atomic(directory / "main.md", _project_stub_text(project_id))
        else:
            record = _record(yaml_path, "project", project_id)
        if not subproject_id:
            return
        subproject_id = _slug(subproject_id, "subproject")
        subprojects = record.setdefault("subprojects", {})
        if not isinstance(subprojects, dict):
            raise ValueError(f"invalid subprojects for project {project_id}")
        if subproject_id in subprojects:
            return
        markdown_path = directory / f"{subproject_id}.md"
        if markdown_path.exists():
            raise FileExistsError(
                f"subproject file already exists: {markdown_path}"
            )
        subprojects[subproject_id] = {
            "kind": "regular", "file": markdown_path.name, "parent": "main",
        }
        record["last_updated"] = time.time()
        _write_atomic(
            markdown_path, _subproject_stub_text(project_id, subproject_id),
        )
        _write_atomic(yaml_path, _dump_yaml(record))


def add_decision(path: Path, text: str) -> str:
    """
    Prepend one timestamped bullet to a project or subproject's Decisions
    section, returning the full bullet line written.
    """
    with file_lock(path.with_suffix(path.suffix + ".lock")):
        content = path.read_text()
        line = f"- {time.strftime('%Y-%m-%d %H:%M')} — {text}"
        existing = extract_section(content, "## Decisions")
        lines = existing.splitlines()[1:] if existing else []
        while lines and not lines[0].strip():
            lines = lines[1:]
        new_block = "\n".join(["## Decisions", "", line] + lines)
        content = replace_section(content, "## Decisions", new_block)
        _write_atomic(path, content)
    return line


def register_discovered_repositories(
    target: MemoryTarget, paths: list[str], workspace: str,
) -> dict[str, Path]:
    """
    Detect git repositories among touched paths that aren't yet registered
    for a project target, create their repository records if missing, add
    them to the project's repositories list, and return their main records.
    """
    if not paths or target.kind != "project":
        return {}
    root = docs_root(workspace)
    known_roots = set()
    for repo_id in target.repository_ids:
        directory = root / "repositories" / repo_id
        record = _record(directory / f"{repo_id}.yaml", "repository", repo_id)
        checkout_value = record.get("checkout", "")
        if isinstance(checkout_value, str) and checkout_value:
            checkout = Path(checkout_value)
            if checkout.is_absolute() and checkout.is_dir():
                known_roots.add(checkout.resolve())

    discovered = {}
    for value in paths:
        source = Path(value)
        if not source.is_absolute():
            source = Path(workspace) / source
        git_root = _git_root(source)
        if git_root is None or git_root in known_roots:
            continue
        known_roots.add(git_root)
        repo_id = _register_repository(root, git_root)
        if repo_id is None:
            continue
        _add_project_repository(root, target.project_id, repo_id)
        repo_dir = root / "repositories" / repo_id
        repo_record = _record(repo_dir / f"{repo_id}.yaml", "repository", repo_id)
        discovered[repo_id] = _markdown_path(
            repo_dir, repo_record.get("main", "memory.md"),
        )
    return discovered
