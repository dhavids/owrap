import json
import os
import sys

from ..utils.paths import session_ctx_touched_path
from ..utils.session.session_resolver import owrap_sid_for_ccsid


class TouchedRunner:
    """
    Record file paths the planner touched (item 14) for the next context-
    manager dispatch to pick up, as an alternative to transcript mining —
    the planner reports what changed instead of owrap inferring it.
    """

    def run(self, paths: list, note: str = None):
        """
        Append `paths` (each with the same optional one-line `note`) to
        this window's pending-touched-paths file.
        """
        ccsid = os.environ.get("CLAUDE_CODE_SESSION_ID", "").strip()
        if not ccsid:
            print("No CLAUDE_CODE_SESSION_ID — run this from an attached window")
            sys.exit(1)

        owrap_sid = owrap_sid_for_ccsid(ccsid)
        if not owrap_sid:
            print("No owrap session attached to this window — run `owrap attach` first")
            sys.exit(1)

        touched_path = session_ctx_touched_path(owrap_sid, ccsid)
        touched_path.parent.mkdir(parents=True, exist_ok=True)
        entries = []
        if touched_path.exists():
            try:
                entries = json.loads(touched_path.read_text())
            except (json.JSONDecodeError, OSError):
                entries = []

        for path in paths:
            entries.append({"path": path, "note": note or ""})

        touched_path.write_text(json.dumps(entries))
        plural = "s" if len(paths) != 1 else ""
        print(f"TOUCHED {len(paths)} path{plural} queued for the next context update")
