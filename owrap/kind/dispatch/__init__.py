from ...actions.access import Access
from ...actions.run.start import Start
from ...dispatch import work


class Dispatch(Access, Start):
    """
    Base for every kind whose main verb is dispatching work rather
    than editing a stored record. `read`/`exec`/`task`/`agent`/`f`
    dispatch one synchronous unit of work into the attached
    session's server and block until it finishes; `ctx`/`updr`
    queue a background worker and return, mixing in `Wait` and
    overriding `get` with their own facets instead of this class's
    task-id lookup.

    Each concrete kind overrides `start` directly. `get` is shared
    logic every other kind in this shape gets for free: look up one
    of this kind's own tasks by id in `owrap/dispatch/work.py`'s
    sentinel records. `Task` reuses the same lookup unscoped, across
    every kind's tasks rather than one.
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
