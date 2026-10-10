from ...actions.access import Access
from ...actions.run.start import Start
from ...dispatch import work


class Dispatch(Access, Start):
    """
    Base for every kind that dispatches one synchronous unit of work
    into the attached session's server and blocks until it finishes
    (`read`/`exec`/`task`/`agent`/`f`) -- not a new action type, just
    a new *shape*: `start`/`get` already exist on `Start`/`Access`,
    reused here rather than invented. Each concrete kind overrides
    `start` directly (its own args never fit the generic `_on_start`
    callback shape), but `get` is real shared logic every one of
    them gets for free: look up one of *this kind's own* tasks by
    id in `owrap/dispatch/work.py`'s sentinel records. `Task`
    (cross-cutting abort/status over whatever any `Dispatch` kind
    wrote to RUNNING_DIR) sits alongside this, not under it -- it
    dispatches nothing itself, and reuses the same lookup unscoped
    (any kind's task, not just one).
    """

    kind = ""


    # Public Methods

    def get(self, task_id: str = None) -> None:
        """
        Report this kind's own dispatched task's status by id:
        still running (with liveness), or its recorded outcome if
        already finished.
        """
        if task_id is None:
            self._usage("get")
        data = work.find_task(task_id, kind=self.kind)
        if data is None:
            self._fail(f"no {self.kind} task found with id {task_id}")
        print(work.format_task_status(data))
