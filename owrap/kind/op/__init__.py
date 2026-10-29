from ...actions.access import Access
from ...actions.modify import Modify


class Op(Modify, Access):
    """
    Base for a kind that acts on one implicit target (the current
    workspace's config or permission state) with no live session and no
    async dispatch. Binds `Modify`/`Access` for `set`/`get`; each concrete
    kind defines its own `do`, run when the kind is invoked with no action
    word.
    """
