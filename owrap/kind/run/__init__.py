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
    Base for kinds whose actions trigger or mutate live process or
    session state (today: daemon, session, project, worktree). Binds
    `Modify` with the run-specific verbs (`start`/`stop`/`restart`/
    `attach`/`detach`/`refresh`/`kill`/`clean`/`wait`), which live in
    `actions/run/` as plain mixins.
    """


    # Private Methods

    def _default_get(self) -> None:
        """
        Fallback for `get` called with no args at all. A concrete
        kind overrides this with whatever "status" means for it
        (e.g. `Daemon` reports its own pid).
        """
        raise ValueError(f"{self.kind} does not support get")
