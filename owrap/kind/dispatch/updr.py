import os

from . import Dispatch
from ...actions.run.wait import Wait
from ...ctx import manual
from ...ctx.dispatch import run_manual, wait_for_job
from ...ctx.state import (
    ctx_dispatch_status, format_last_dispatch, queue_touched_paths,
)
from ...utils.session.resolver import _parse, session_file
from ...utils.memory.records import resolve_memory_target
from ...utils.parser.text import preview_lines


class Updr(Dispatch, Wait):
    """
    Dispatch an Update Protocol task for the window's attached session
    (its project/subproject or repository record), optionally combined
    with Update Context in the same dispatch. `start`/`done` call
    `owrap.ctx`.
    """

    kind = "updr"

    usage = {
        "start": {
            "usage": "[<subproject>] [--ctx]",
            "args": [
                ("subproject", "subproject to update; defaults to this "
                               "session's target"),
                ("ctx", "also run Update Context in the same dispatch"),
            ],
            "examples": ["", "docs", "docs --ctx"],
            "purpose": "Queue durable record updates, optionally with context",
            "group": "record",
        },
        "done": {
            "usage": "[--error <reason>]",
            "args": [
                ("error", "report the manual update failed, with this "
                          "reason, instead of marking it done"),
            ],
            "examples": ["", "--error 'opencode down'"],
        },
        "add": {
            "usage": "<path> [path...] [--note <text>]",
            "args": [
                ("path", "a file path touched this window"),
                ("note", "optional one-line note, applied to every path"),
            ],
            "examples": ["owrap", "owrap owrap/cli.py"],
        },
        "get": {
            "usage": "[memory]",
            "args": [
                ("memory", "print every repository record linked to this "
                           "session's project, instead of the project/"
                           "repository record itself"),
            ],
            "examples": ["", "memory"],
        },
        "wait": {
            "usage": "<job_id> [<timeout>]",
            "args": [
                ("job_id", "the job id `start` printed"),
                ("timeout", "seconds to wait; defaults to 300"),
            ],
            "examples": ["7f67b3760d", "7f67b3760d 60"],
        },
    }

    messages = {
        "add": "TOUCHED {count} path{plural} queued for the next protocol update",
        "get": "{text}",
        "wait": "{message}",
    }


    # Public Methods

    def start(self, subproject: str = None, ctx: bool = False) -> None:
        """
        Queue a background Update Protocol dispatch for this window,
        or both halves at once if `ctx` is set.
        """
        mode = None if ctx else "updr"
        run_manual(mode=mode, subproject=subproject)

    def done(self, error: str = None) -> None:
        """
        Mark this window's manual (opencode-down) update as complete,
        or failed if `error` is given.
        """
        manual.done(error=error)

    def add(self, *paths, note: str = None) -> None:
        """
        Queue one or more touched file paths for the next protocol update,
        each with the same optional one-line `note`. Feeds the same queue as
        `Ctx.add`.
        """
        if not paths:
            self._usage("add")
        count = self._edit(queue_touched_paths, paths, note=note)
        self._ok("add", count=count, plural="s" if count != 1 else "")

    def get(self, what: str = None) -> None:
        """
        Print every repository record linked to this session's
        project -- `get`'s only argument-driven case (the bare form
        is `_default_get`, the project/repository record itself).
        """
        if what != "memory":
            self._usage("get")
        sid, target = self._session_target()
        if not target.repository_paths:
            self._fail(f"session '{sid}' has no linked repositories")
        blocks = []
        for path in target.repository_paths:
            content = path.read_text().strip() if path.exists() else "(missing)"
            blocks.append(f"# memory: {path}\n{preview_lines(content)}")
        self._ok("get", text="\n\n".join(blocks))


    # Private Methods

    def _session_target(self):
        """
        Resolve the attached session's id and project/repository
        `MemoryTarget`, failing cleanly if either step comes up empty.
        """
        sid = os.environ.get("SESSION_ID", "").strip()
        if not sid:
            self._fail("no SESSION_ID — run this from an attached window")
        session = self._edit(_parse, session_file(sid))
        target = self._edit(resolve_memory_target, session)
        if target is None:
            self._fail(f"session '{sid}' has no project/repository target")
        return sid, target

    def _default_get(self) -> None:
        """
        Report this session's project/subproject or repository
        record path, its last ctx/updr dispatch status (plus when it
        last ran, if it's finished), and -- unless one is still
        running -- a preview of the record. `get`'s whole meaning
        for a kind with no stored items to index into.
        """
        sid, target = self._session_target()
        path = target.project_path or target.repository_paths[0]
        status = ctx_dispatch_status(sid)
        if status == "running":
            self._ok("get", text=f"{path}\nstatus: {status}")
            return
        last_run = format_last_dispatch(sid)
        last_line = f"\n{last_run}" if last_run else ""
        content = path.read_text() if path.exists() else "(no record yet)"
        self._ok(
            "get",
            text=f"{path}\nstatus: {status}{last_line}\n\n{preview_lines(content)}",
        )

    def _on_wait(self, job_id: str = None, timeout: int = None) -> dict:
        """
        Block until `job_id` (as `start` printed it) finishes.
        """
        if job_id is None:
            self._usage("wait")
        job = self._edit(wait_for_job, job_id, timeout)
        return {"message": f"{job.get('status')} (rc={job.get('rc')})"}
