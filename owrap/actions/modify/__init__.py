from .. import Actions
from .add import Add
from .clear import Clear
from .done import Done
from .remove import Remove
from .restore import Restore
from .set import Set
from .update import Update


class Modify(Actions, Update, Set, Remove, Add, Clear, Done, Restore):
    """
    The base-most modify-capable action type: anything with its own
    direct identity, resolved by the kind itself rather than through
    a session. Exposes `update`/`set`/`remove`/`add`/`clear`/`done`/
    `restore` -- every verb that acts on an identified thing's data,
    regardless of what shape that thing is (a markdown line-item, a
    project record, a live process). A kind overrides whichever of
    these it needs with its own logic; unused ones stay refusing
    stubs. `Run` adds its own live-process verbs on top.
    """
