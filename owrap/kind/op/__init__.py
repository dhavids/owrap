from ...actions.access import Access
from ...actions.modify import Modify


class Op(Modify, Access):
    """
    Base for a kind that acts on one implicit target -- the current
    workspace's own config or permission state -- rather than a
    resolved record id, with no live session and no async dispatch
    of its own. Binds `Modify`/`Access` for `set`/`get`; each
    concrete kind also defines its own `do`, the single action that
    runs when the kind is invoked with no action word at all.
    """
