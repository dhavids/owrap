import os
import sys

from owrap.utils.session.resolver import owrap_sid_for_ccsid


class TouchedRunner:
    """
    Record file paths the planner touched (item 14) for the next context-
    manager dispatch to pick up, as an alternative to transcript mining —
    the planner reports what changed instead of owrap inferring it.
    """

    def run(self, paths: list, note: str = None):
        """
        Append `paths` (each with the same optional one-line `note`) to
        this window's pending-touched entries in ctx_state.json.
        """
        ccsid = os.environ.get("CLAUDE_CODE_SESSION_ID", "").strip()
        if not ccsid:
            print("No CLAUDE_CODE_SESSION_ID — run this from an attached window")
            sys.exit(1)

        owrap_sid = owrap_sid_for_ccsid(ccsid)
        if not owrap_sid:
            print("No owrap session attached to this window — run `owrap attach` first")
            sys.exit(1)

        from .context_manager import append_touched_entries
        entries = [{"path": path, "note": note or ""} for path in paths]
        append_touched_entries(owrap_sid, ccsid, entries)
        plural = "s" if len(paths) != 1 else ""
        print(f"TOUCHED {len(paths)} path{plural} queued for the next context update")
