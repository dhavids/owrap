from .rename import RenameRunner
from .todo import TodoRunner
from ..utils.actions import Record, NestedRecord, SectionEntry


class Project(Record):
    """
    A project record: its own directory + `<id>.yaml` under
    `docs_root/projects/`.
    """

    kind = "project"

    def __init__(self):
        self._rename = RenameRunner()

    def update(self, old_id: str, new_id: str) -> str:
        self._rename.project(old_id, new_id)
        return f"Renamed project {old_id} -> {new_id}"


class Repository(Record):
    """
    A repository record: its own directory + `<id>.yaml` under
    `docs_root/repositories/`.
    """

    kind = "repository"

    def __init__(self):
        self._rename = RenameRunner()

    def update(self, old_id: str, new_id: str) -> str:
        self._rename.repository(old_id, new_id)
        return f"Renamed repository {old_id} -> {new_id}"


class Subproject(NestedRecord):
    """
    A subproject: an entry in its project's `subprojects:` yaml map,
    with a markdown file in the project's own directory.
    """

    kind = "subproject"

    def __init__(self):
        self._rename = RenameRunner()

    def update(self, project_id: str, old_id: str, new_id: str = None) -> str:
        if new_id is None:
            raise ValueError(
                "Usage: owrap update subproject <project_id> <old> <new>"
            )
        self._rename.subproject(project_id, old_id, new_id)
        return f"Renamed subproject {project_id}/{old_id} -> {new_id}"


class Todo(SectionEntry):
    """
    A goal line-item under a project/subproject's `## Goals` section.
    """

    kind = "todo"

    def __init__(self):
        self._todo = TodoRunner()

    def update(self, target: str, position: str, text: str = None) -> None:
        # run_update prints its own result/usage and exits on error.
        self._todo.run_update(target, position, text)


KIND_REGISTRY = {
    "project": Project,
    "repository": Repository,
    "subproject": Subproject,
    "todo": Todo,
}
