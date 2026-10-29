from .. import Actions
from .get import Get


class Access(Actions, Get):
    """
    Action type for read-only operations. A kind defining `read` (its
    structured data) gets position-indexed `get`; a kind whose read access
    has another shape overrides `get` directly.
    """

    def _path(self, target: str = None):
        """
        Resolve the target and report its record's own file path --
        a property of the kind, not a dispatchable verb. Used as the
        default fallback for actions like `get` when called with no
        args at all (see `_default_<action>` on `dispatch()`).
        """
        memory_target = self._resolve_target(target)
        self._ok("path", path=memory_target.project_path)
