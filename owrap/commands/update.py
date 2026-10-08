from .rename import RenameRunner
from ..utils.memory.records import normalize_identity_kind


class UpdateRunner:
    """
    Change an existing record's id, dispatched by kind. Today this is
    project/subproject/repository renaming (delegated to RenameRunner);
    other kinds (e.g. todo's position-text replace) join this dispatch
    as they migrate off their own standalone commands.
    """

    def __init__(self):
        self._rename = RenameRunner()

    def run(self, kind: str, arg1: str, arg2: str, arg3: str = None) -> str:
        """
        Dispatch one update by kind, returning the success message to
        print. Raises ValueError for an unhandled kind or a missing
        required argument.
        """
        kind = normalize_identity_kind(kind)
        if kind == "project":
            self._rename.project(arg1, arg2)
            return f"Renamed project {arg1} -> {arg2}"
        if kind == "repository":
            self._rename.repository(arg1, arg2)
            return f"Renamed repository {arg1} -> {arg2}"
        if kind == "subproject":
            if arg3 is None:
                raise ValueError(
                    "Usage: owrap update subproject <project_id> <old> <new>"
                )
            self._rename.subproject(arg1, arg2, arg3)
            return f"Renamed subproject {arg1}/{arg2} -> {arg3}"
        raise ValueError(f"update does not handle kind '{kind}'")
