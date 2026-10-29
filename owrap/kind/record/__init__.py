from .identity import current_workspace
from ...actions.access import Access
from ...actions.modify import Modify


class Record(Modify, Access):
    """
    Base for a kind with its own stored identity (a directory and
    `<id>.yaml` record under `docs_root`) and no live session or process.
    Binds `Modify`/`Access` and provides `_workspace`, which resolves the
    workspace for the concrete kinds. Each kind overrides its verbs
    directly.
    """


    # Private Methods

    def _workspace(self, workspace: str = None) -> str:
        """
        `workspace` if given, else the attached session's own
        workspace (`""` if there is no attached session).
        """
        return workspace or current_workspace()
