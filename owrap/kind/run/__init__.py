from ...actions.modify import Modify
from ...actions.run.attach import Attach
from ...actions.run.clean import Clean
from ...actions.run.detach import Detach
from ...actions.run.kill import Kill
from ...actions.run.refresh import Refresh
from ...actions.run.restart import Restart
from ...actions.run.start import Start
from ...actions.run.stop import Stop
from ...actions.run.wait import Wait


class Run(Modify, Start, Stop, Restart, Attach, Detach, Refresh, Kill, Clean, Wait):
    """
    Base for every kind whose actions trigger or mutate live process
    or session state rather than a stored record (today: daemon,
    session, project, worktree). `Run` isn't an action type itself -- same
    as `Entry`, it's this kind-level base that binds `Modify` (and
    everything it already carries: `add`/`update`/`remove`/`clear`/
    `done`/`restore`/`set`) together with the run-specific verbs
    (`start`/`stop`/`restart`/`attach`/`detach`/`refresh`/`kill`/
    `clean`/`wait`) a kind in this shape needs; the verbs themselves
    stay in `actions/run/` as plain mixins.
    """


    # Private Methods

    def _default_get(self) -> None:
        """
        Fallback for `get` called with no args at all. A concrete
        kind overrides this with whatever "status" means for it
        (e.g. `Daemon` reports its own pid).
        """
        raise ValueError(f"{self.kind} does not support get")
