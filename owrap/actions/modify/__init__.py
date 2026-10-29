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
    Base action type for kinds with their own direct identity, resolved
    by the kind itself. Exposes `update`/`set`/`remove`/`add`/`clear`/
    `done`/`restore`; verbs a kind doesn't override refuse. `Run` adds
    live-process verbs.
    """
