from .branch import BranchRunner
from .decide import DecideRunner
from .project import ProjectRunner
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
        self._project = ProjectRunner()

    def add(self, name: str, force: bool = False) -> None:
        # Still selects the session onto it too — splitting that out is phase 6's job.
        self._project.sub(name, force)

    def update(self, project_id: str, old_id: str, new_id: str = None) -> str:
        if new_id is None:
            raise ValueError(
                "Usage: owrap update subproject <project_id> <old> <new>"
            )
        self._rename.subproject(project_id, old_id, new_id)
        return f"Renamed subproject {project_id}/{old_id} -> {new_id}"


class Branch(Subproject):
    """
    A branch subproject: a `kind: branch` entry in its project's
    `subprojects:` yaml map, linked to a parent and a repository ref.
    """

    kind = "branch"

    def __init__(self):
        super().__init__()
        self._branch = BranchRunner()

    def add(
        self, project_id: str, branch_id: str, parent_id: str,
        repository_id: str, branch_ref: str,
    ) -> str:
        path = self._branch.create(
            project_id, branch_id, parent_id, repository_id, branch_ref,
        )
        return f"Created branch record: {path}\nGit branch unchanged."


class Todo(SectionEntry):
    """
    A goal line-item under a project/subproject's `## Goals` section.
    """

    kind = "todo"

    def __init__(self):
        self._todo = TodoRunner()

    def add(self, target: str, arg2: str, arg3: str = None) -> None:
        # run prints its own result/usage and exits on error.
        self._todo.run(target, arg2, arg3)

    def update(self, target: str, position: str, text: str = None) -> None:
        # run_update prints its own result/usage and exits on error.
        self._todo.run_update(target, position, text)

    def clear(self, target: str = None) -> None:
        # run_clear prints its own result.
        self._todo.run_clear(target)


class Decision(SectionEntry):
    """
    A timestamped decision line-item under a project/subproject's
    `## Decisions` section.
    """

    kind = "decision"

    def __init__(self):
        self._decide = DecideRunner()

    def add(self, target: str, text: str = None) -> None:
        # run prints its own result/usage and exits on error.
        self._decide.run(target, text)


KIND_REGISTRY = {
    "project": Project,
    "repository": Repository,
    "subproject": Subproject,
    "branch": Branch,
    "todo": Todo,
    "decision": Decision,
}
