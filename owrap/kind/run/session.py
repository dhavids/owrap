import os
import time

from . import Run
from ...dispatch.manager import Manager
from ...session.attach import attach as attach_fn
from ...session.start import (
    refresh as refresh_fn, restart as restart_fn, start as start_fn,
)
from ...session.stop import force_stop as force_stop_fn, stop as stop_fn
from .daemon import Daemon
from ...session.workflow import SessionWorkflow
from ...utils.session.resolver import _parse, attached_ccsids, detach, session_file
from ...utils.session.trash import restore_from_trash
from ...utils.paths import session_input


class Session(Run):
    """
    The canonical session-lifecycle kind.
    """

    kind = "session"

    usage = {
        "add": {
            "usage": "[temp] [<label>]",
            "args": [
                ("temp", "reserved keyword -- mint a parentless scratch "
                         "session instead of a child of the current one"),
                ("label", "optional name for the new session"),
            ],
            "examples": ["", "my-child", "temp", "temp my-scratch"],
            "purpose": "Create a child session with inherited target, or an "
                   "independent one via `temp`",
            "group": "session",
        },
        "done": {
            "usage": "[<sid>] [apply]",
            "args": [
                ("sid", "child session id; defaults to the attached session"),
                ("apply", "reserved keyword -- without it, preview only"),
            ],
            "examples": ["", "apply"],
            "purpose": "Preview or merge child context",
            "group": "session",
        },
        "restore": {
            "usage": "<sid>",
            "args": [
                ("sid", "trashed session id to restore"),
            ],
            "examples": ["abc123"],
        },
        "wait": {
            "usage": "[<timeout>]",
            "args": [("timeout", "seconds to wait; defaults to 120")],
            "examples": ["", "60"],
            "purpose": "Wait for queued input to clear",
            "group": "dispatch",
        },
        "attach": {
            "usage": "<target>",
            "args": [("target", "session, project, or repository id")],
            "examples": ["abc123"],
            "purpose": "Bind this window to a session",
            "group": "session",
        },
        "refresh": {
            "usage": "",
            "args": [],
            "examples": [""],
            "purpose": "Refresh session context and orientation",
            "group": "session",
        },
        "stop": {
            "usage": "[force]",
            "args": [("force", "reserved keyword -- stop every session and "
                               "kill all tasks/servers/the daemon instead "
                               "of just this one")],
            "examples": ["", "force"],
            "purpose": "Stop the current session (reversible via `owrap "
                   "session restore`)",
            "group": "session",
        },
    }

    messages = {
        "detach": "DETACHED session={sid}  still_attached={remaining}",
        "stop": "{text}",
        "wait": "{message}",
    }


    # Public Methods

    def add(self, arg1: str = None, arg2: str = None) -> None:
        """
        Spawn a child session inheriting the current session's
        identity -- or, if `arg1` is the reserved keyword `temp`,
        mint a standalone, parentless scratch session instead.
        """
        if arg1 == "temp":
            mode, label = "temp", arg2
        else:
            mode, label = "spawn", arg1
        try:
            data = SessionWorkflow().create(mode, label or "")
        except (ValueError, FileNotFoundError) as exc:
            self._fail(exc)
        noun = "Temporary session" if mode == "temp" else "Child session"
        print(f"{noun}: {data['session_id']} ({data['session_name']})")
        print(f"__OWRAP_EXPORT__ SESSION_ID={data['session_id']}")

    def done(self, sid: str = None, apply: str = None) -> None:
        """
        Collapse the current (or named) child session's context into
        its parent -- preview only unless `apply` is given. A branch
        session's own `done` (merging its Git worktree refs) is
        `Worktree.done` instead.
        """
        self._collapse(sid or "", apply=apply == "apply")

    def restore(self, session_id: str = None) -> None:
        """
        Restore a trashed session back to its live location.
        """
        if not session_id:
            self._usage("restore")
        try:
            restore_from_trash(session_id)
        except FileNotFoundError as exc:
            self._fail(exc)
        print(
            f"OWRAP RESTORED  session: {session_id}  (run `owrap session "
            f"attach {session_id}` to bind this window to it)"
        )

    def attach(self, target_session_id: str = None) -> None:
        """
        Attach to the given session id, project id, or repository id.
        """
        attach_fn(self, target_session_id)

    def start(self, project_name: str = None) -> None:
        """
        Resolve/mint a session, bootstrap it, and print its
        orientation banner. A bare `project_name` is always a project
        id; subproject targeting is `owrap project add`/`owrap
        project set` after start.
        """
        start_fn(Manager(), project_name=project_name)

    def restart(self, project_name: str = None) -> None:
        """
        Stop the current session and start a fresh one.
        """
        restart_fn(Manager(), project_name=project_name)

    def refresh(self, project_name: str = None) -> None:
        """
        Refresh this session's context and print its orientation banner.
        """
        refresh_fn(Manager(), project_name=project_name)


    # Private Methods

    def _default_get(self) -> None:
        """
        Print this session's identity fields as a table -- `get`'s
        whole meaning for a kind with no stored items to index into.
        """
        sid = os.environ.get("SESSION_ID", "").strip()
        if not sid:
            self._fail("no SESSION_ID — run this from an attached window")
        sf = session_file(sid)
        if not sf.exists():
            self._fail(f"no active session for {sid}")
        data = _parse(sf)
        fields = (
            "session_id", "target_kind", "project_id", "subproject_id",
            "repository_id", "repositories", "workspace", "started",
            "last_refresh",
        )
        width = max(len(f) for f in fields)
        print(f"# session: {sf}")
        for field in fields:
            print(f"  {field:<{width}}  {data.get(field, '—')}")

    def _on_wait(self, timeout: int = None) -> dict:
        """
        Block until this session's queued input is consumed, or
        fail once `timeout` seconds pass (default 120).
        """
        deadline = time.time() + (int(timeout) if timeout else 120)
        input_path = session_input(os.environ.get("OWRAP_SESSION", ""))
        while time.time() < deadline:
            if not input_path.exists() or input_path.stat().st_size == 0:
                return {"message": "input clear"}
            time.sleep(0.5)
        self._fail("timed out waiting for input to clear")

    def _on_stop(self, arg1: str = None) -> dict:
        """
        Stop the current (or named) session and move it to the
        trash -- or, if `arg1` is the reserved keyword `force`, kill
        every running task/server/daemon process and move every
        session to the trash instead.
        """
        if arg1 == "force":
            kill = Daemon()._on_kill()
            count = force_stop_fn()
            plural = "s" if count != 1 else ""
            text = (
                f"OWRAP STOPPED  {kill['message']}  {count} session{plural} "
                f"moved to .trash (restore any with `owrap session restore "
                f"<session_id>`)"
            )
            return {"text": text}
        message, _ = stop_fn(arg1)
        return {"text": message}

    def _on_detach(self) -> dict:
        """
        Detach this window from its session without affecting any
        other window still attached to it.
        """
        window_id = (
            os.environ.get("CLAUDE_CODE_SESSION_ID", "").strip()
            or os.environ.get("CODEX_SESSION_ID", "").strip()
        )
        sid = detach()
        if not sid:
            self._fail("not attached to any session")

        from ...ctx.state import prune_ctx_state_window
        prune_ctx_state_window(sid, window_id)

        remaining = len(attached_ccsids(sid))
        return {"sid": sid, "remaining": remaining}

    def _collapse(self, sid: str, apply: bool) -> None:
        """
        Preview or apply merging a child session's context into its
        parent -- `done`'s whole job now that it no longer also
        handles branch sessions.
        """
        try:
            result = SessionWorkflow().collapse(sid, apply)
        except (ValueError, FileNotFoundError) as exc:
            self._fail(exc)
        except TypeError:
            self._fail(self.target_messages["no_target"])
        print(f"Child {result['child']} -> parent {result['parent']}")
        for heading, entries in result["entries"].items():
            print(f"{heading}: {len(entries)} new entries")
            for entry in entries:
                print(f"  {entry}")
        print("Collapse applied." if result["applied"] else
              "Preview only. Pass 'apply' to collapse.")
