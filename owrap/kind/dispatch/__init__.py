from ...actions.access import Access
from ...actions.run.start import Start
from ...dispatch import work


class Dispatch(Access, Start):
    """
    Base for kinds whose main verb is dispatching work. `read`/`exec`/
    `task`/`agent`/`f` run one synchronous unit of work in the attached
    session's server and block until it finishes; `ctx`/`updr` queue a
    background worker and return, with their own `get` facets.

    Each concrete kind overrides `start`. `get` looks up one of the
    kind's own tasks by id in `owrap/dispatch/work.py`'s sentinel
    records.
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
