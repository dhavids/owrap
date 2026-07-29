import json
import os
import signal
import sys

from ..base import BaseRunner
from ..utils.paths import RUNNING_DIR


class FinishRunner(BaseRunner):

    def run(self, target, session_id=None):
        if session_id is None:
            session_id = self.manager.session_id or os.environ.get("OWRAP_SESSION", "")

        if not RUNNING_DIR.exists():
            print(f"owrap finish: no running jobs found")
            sys.exit(1)

        matched = []
        for f in sorted(RUNNING_DIR.iterdir()):
            if f.suffix != ".json":
                continue
            try:
                data = json.loads(f.read_text())
            except Exception:
                continue
            if session_id and data.get("session_id") != session_id:
                continue
            kind = data.get("kind", "")
            task_id = str(data.get("task_id", ""))
            if _target_matches(target, kind, task_id):
                matched.append((f, data))

        if not matched:
            print(f"owrap finish: no running job matching '{target}' for session {session_id}")
            sys.exit(1)

        killed = 0
        for sentinel_path, data in matched:
            pid = data.get("pid")
            title = data.get("title", "?")
            kind = data.get("kind", "task")
            task_id = data.get("task_id", "?")
            label = f"{kind}{task_id}"

            if not pid:
                print(f"  {label}: no PID in sentinel, skipping")
                continue

            try:
                os.kill(pid, 0)
            except OSError:
                print(f"  {label} (pid={pid}): already done")
                try:
                    sentinel_path.unlink()
                except Exception:
                    pass
                continue

            try:
                os.kill(pid, signal.SIGTERM)
                print(f"  sent SIGTERM to {label} (pid={pid})  \"{title}\"")
                killed += 1
            except ProcessLookupError:
                print(f"  {label} (pid={pid}): process not found")
            except PermissionError:
                print(f"  {label} (pid={pid}): permission denied")

        if killed == 0:
            sys.exit(1)


def _target_matches(target, kind, task_id):
    t = target.lower()
    if t == "exec":
        return kind == "exec"
    if t.startswith("task"):
        suffix = t[4:]
        return kind == "task" and (suffix == "" or task_id == suffix)
    if t.startswith("msg"):
        suffix = t[3:]
        return kind == "msg" and (suffix == "" or task_id == suffix)
    if t.startswith("agent"):
        suffix = t[5:]
        return kind == "agent" and (suffix == "" or task_id == suffix)
    return kind == t