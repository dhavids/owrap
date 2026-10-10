from .identity import current_workspace
from ...actions.access import Access
from ...actions.modify import Modify


class Record(Modify, Access):
    """
    Base for a kind with its own stored identity -- a directory and
    `<id>.yaml` record under `docs_root` -- and no live session or
    process of its own. Binds `Modify`/`Access` for this shape, plus
    `_workspace`, the workspace-resolution helper every concrete kind
    here uses (`_edit`, the error-handling helper, lives on `Actions`
    itself since `Run`-based kinds need it too). Each concrete kind
    overrides its own verbs directly rather than through `Modify`'s
    `_add`/`_update`/etc. callbacks.
    """


    # Private Methods

    def _workspace(self, workspace: str = None) -> str:
        """
        `workspace` if given, else the attached session's own
        workspace (`""` if there is no attached session).
        """
        return workspace or current_workspace()
