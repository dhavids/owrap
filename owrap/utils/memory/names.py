"""
Project and subproject name lookup and the rules for new names.

A bare name resolves to a project or a subproject; `project/sub` (or
`project/main` for the project's own record) always names one exactly.
"""

from .records import _record, docs_root
from ..constants import RESERVED_WORDS


def reserved_names() -> frozenset:
    """
    Return every word a new project or subproject may not be named:
    owrap's kinds, kind aliases, actions, the `get project` facet words,
    and `RESERVED_WORDS`.
    """
    from ...kind import ACTION_REGISTRY, KIND_ALIASES, KIND_REGISTRY
    from ...kind.run.project import Project

    return frozenset(
        set(KIND_REGISTRY) | set(KIND_ALIASES) | set(ACTION_REGISTRY)
        | set(Project.facets()) | set(RESERVED_WORDS)
    )


def project_index(workspace: str) -> dict:
    """
    {project_id: [subproject ids]} for every project record under the
    workspace's docs root.
    """
    projects = docs_root(workspace) / "projects"
    index = {}
    if not projects.is_dir():
        return index
    for directory in sorted(p for p in projects.iterdir() if p.is_dir()):
        yaml_path = directory / f"{directory.name}.yaml"
        if not yaml_path.is_file():
            continue
        record = _record(yaml_path, "project", directory.name)
        subprojects = record.get("subprojects")
        index[directory.name] = (
            sorted(subprojects) if isinstance(subprojects, dict) else []
        )
    return index


def find_target(workspace: str, token: str) -> tuple:
    """
    Resolve `token` to (project_id, subproject_id) -- subproject_id is
    "" for a project's own record. Fails listing the candidates when the
    name is ambiguous or unknown.
    """
    index = project_index(workspace)
    if "/" in token:
        project_id, _, sub = token.partition("/")
        if project_id not in index:
            raise ValueError(f"no project '{project_id}'")
        if sub in ("", "main"):
            return project_id, ""
        if sub not in index[project_id]:
            raise ValueError(
                f"no subproject '{sub}' in {project_id}; it has: "
                f"{', '.join(index[project_id]) or 'none'}"
            )
        return project_id, sub
    if token in ("main", "sub"):
        raise ValueError(
            f"'{token}' is retired -- name the project, or project/sub"
        )
    hits = [(token, "")] if token in index else []
    hits += [(p, token) for p, subs in index.items() if token in subs]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise ValueError(
            f"no project or subproject '{token}'. Projects: "
            f"{', '.join(index) or 'none'}"
        )
    lines = [
        f"  {p}/main  (project {p})" if not s else f"  {p}/{s}  (subproject of {p})"
        for p, s in hits
    ]
    raise ValueError(
        f"'{token}' is ambiguous -- use one of:\n" + "\n".join(lines)
    )


def check_new_name(workspace: str, name: str, label: str) -> None:
    """
    Refuse a new project or subproject name that is reserved (an owrap
    kind, action, alias, or facet word) or already used by any project
    or subproject. Existing records are never re-checked.
    """
    if name in reserved_names():
        raise ValueError(
            f"'{name}' is reserved by owrap and can't name a {label}"
        )
    for project_id, subs in project_index(workspace).items():
        if name == project_id or name in subs:
            raise ValueError(
                f"'{name}' is already used in {project_id}; project and "
                "subproject names must be unique"
            )


def name_notices(workspace: str, only: tuple = ()) -> list:
    """
    Return warning lines for existing names that are reserved or used by
    more than one project/subproject. `only` limits them to names
    involving those ids.
    """
    index = project_index(workspace)
    reserved = reserved_names()
    owners = {}
    for project_id, subs in index.items():
        owners.setdefault(project_id, []).append(f"{project_id}/main")
        for sub in subs:
            owners.setdefault(sub, []).append(f"{project_id}/{sub}")
    notices = []
    for name, where in sorted(owners.items()):
        if only and name not in only:
            continue
        if name in reserved:
            notices.append(
                f"'{name}' ({', '.join(where)}) is reserved by owrap -- "
                "rename it"
            )
        elif len(where) > 1:
            notices.append(
                f"'{name}' is used by {', '.join(where)} -- refer to it "
                "as project/sub"
            )
    return notices
