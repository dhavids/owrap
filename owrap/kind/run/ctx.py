import argparse
import os
import sys
from pathlib import Path

from . import Run
from ...ctx import manual
from ...ctx.dispatch import hook_run, run, run_manual, wait_for_job
from ...ctx.state import (
    ctx_dispatch_status, format_last_dispatch, queue_touched_paths,
)
from ...utils.paths import context_path
from ...utils.parser.text import preview_lines


def main():
    """
    Entry point for a background context-manager worker process --
    replaces `python -m owrap.runner ctx-worker --input <path>` as the
    subprocess target `run_manual`/`hook_run` spawn.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    args = parser.parse_args()
    sys.exit(run(input_path=Path(args.input)))


class Ctx(Run):
    """
    Dispatches an Update Context task for the window's attached session.
    """

    kind = "ctx"

    usage = {
        "start": {
            "usage": "", "args": [], "examples": [],
            "purpose": "Queue a session context update",
            "group": "record",
        },
        "template": {
            "usage": "[subproject]",
            "args": [
                ("subproject", "report this subproject's files instead of "
                               "the session's current target"),
            ],
            "examples": ["", "docs"],
        },
        "get": {
            "usage": "[template [subproject]|hook]",
            "args": [
                ("template", "same as `owrap ctx template` -- the manual "
                             "opencode-down fallback instructions"),
                ("hook", "Harness's PreCompact hook entry point -- "
                         "reads hook payload JSON from stdin, plumbing only"),
            ],
            "examples": ["", "template", "template docs"],
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
        "add": "TOUCHED {count} path{plural} queued for the next context update",
        "get": "{text}",
        "wait": "{message}",
    }


    # Public Methods

    def start(self) -> None:
        """
        Queue a background Update Context dispatch for this window.
        """
        run_manual(mode="ctx")

    def template(self, subproject: str = None) -> None:
        """
        Print the Context/Project/Repository update instructions and
        real file paths for the manual (opencode-down) fallback --
        the planner edits them directly, then runs `done`.
        """
        manual.template(subproject)

    def done(self, error: str = None) -> None:
        """
        Mark this window's manual (opencode-down) context update as
        complete, or failed if `error` is given.
        """
        manual.done(error=error)

    def add(self, *paths, note: str = None) -> None:
        """
        Queue one or more touched file paths for the next context
        update, each with the same optional one-line `note`.
        """
        if not paths:
            self._usage("add")
        count = self._edit(queue_touched_paths, paths, note=note)
        self._ok("add", count=count, plural="s" if count != 1 else "")

    def get(self, what: str = None, *args) -> None:
        """
        Run a plumbing facet by name: `template` (the manual
        opencode-down fallback instructions, forwarding any
        subproject arg) or `hook` (Claude/Codex's PreCompact entry
        point). A bare `owrap ctx get` reaches `_default_get` instead
        (dispatch's own no-args fallback), never this method.
        """
        if what == "template":
            self.template(*args)
        elif what == "hook":
            self._hook()
        else:
            self._usage("get")


    # Private Methods

    def _hook(self) -> None:
        """
        Always prints "{}" and never lets an exception escape --
        compaction must never be blocked by this, regardless of what
        happens inside `hook_run`.
        """
        try:
            hook_run()
        except Exception:
            pass
        print("{}")

    def _default_get(self) -> None:
        """
        Report this session's context.md path, its last ctx/updr
        dispatch status (plus when it last ran, if it's finished),
        and -- unless one is still running -- a preview of context.md.
        """
        sid = os.environ.get("SESSION_ID", "").strip()
        if not sid:
            self._fail("no SESSION_ID — run this from an attached window")
        path = context_path(sid)
        status = ctx_dispatch_status(sid)
        if status == "running":
            self._ok("get", text=f"{path}\nstatus: {status}")
            return
        last_run = format_last_dispatch(sid)
        last_line = f"\n{last_run}" if last_run else ""
        content = path.read_text() if path.exists() else "(no context yet)"
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


if __name__ == "__main__":
    main()
