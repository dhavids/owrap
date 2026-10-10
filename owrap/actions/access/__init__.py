from .. import Actions
from .get import Get


class Access(Actions, Get):
    """
    An action type for read-only operations -- querying something
    without mutating it. A `Document`-shaped kind defines `read`
    (its structured data) and gets `get`'s position-indexed lookup
    for free; a kind whose read access doesn't fit that shape (a
    single record, say, rather than a list) overrides `get` directly
    instead of defining `read`. `read` has no base declaration here
    -- `Get._get` just checks for it with `hasattr`.
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
