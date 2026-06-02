import json
import os
import subprocess
import sys
from pathlib import Path

from ..staging import stage_all
from ..utils.paths import get_workspace_config, RUNTIME_HOME


class SyncRunner:
    """Re-stage templates and dispatch sync_task.md via orun to write planner files."""

    def run(self):
        workspace_name = self._active_workspace()
        if not workspace_name:
            print("Error: no active session. Run `owrap start <name>` first.")
            sys.exit(1)
        config = get_workspace_config(workspace_name)
        if not config.get("workspace"):
            print(f"Error: ~/.owrap/configs/{workspace_name}.json missing `workspace`. Run `owrap setup` first.")
            sys.exit(1)

        staged = stage_all(workspace_name)
        workspace = config["workspace"]
        research_root = config.get("research_root") or f"{workspace}/docs/research"

        # stage_all() already merged planner.md → CLAUDE.md and executor.md → AGENTS.md
        targets = [
            (staged / "self.md",       f"{research_root}/self.md"),
            (staged / "settings.json", f"{workspace}/.claude/settings.local.json"),
        ]

        task_path = self._write_sync_task(targets, workspace_name)
        print(f"sync_task written: {task_path}")
        print(f"staged: {staged}")
        print(f"workspace: {workspace}")
        print(f"research_root: {research_root}")
        print()
        print("Next: planner must dispatch this task via orun. Run:")
        print(f"  ~/bin/orun --input {task_path}")
        sys.exit(0)

    def _active_workspace(self):
        """Read active workspace name from current session file."""
        ccsid = os.environ.get('CLAUDE_CODE_SESSION_ID', '').strip()
        if ccsid:
            ptr = RUNTIME_HOME / 'sessions' / 'by_ccsid' / ccsid
            if ptr.exists():
                sid = ptr.read_text().strip()
                sf = RUNTIME_HOME / 'sessions' / f'{sid}.session'
                if sf.exists():
                    for line in sf.read_text().splitlines():
                        if line.startswith('workspace='):
                            return line.split('=', 1)[1].strip()
        sid = os.environ.get('SESSION_ID', '').strip()
        if not sid:
            cs = Path.home() / '.owrap' / 'current_session'
            if cs.exists():
                sid = cs.read_text().strip()
        if sid:
            sf = RUNTIME_HOME / 'sessions' / f'{sid}.session'
            if sf.exists():
                for line in sf.read_text().splitlines():
                    if line.startswith('workspace='):
                        return line.split('=', 1)[1].strip()
        return None

    def _write_sync_task(self, targets, workspace_name):
        task_dir = RUNTIME_HOME / "docs" / "run" / "tasks"
        task_dir.mkdir(parents=True, exist_ok=True)
        task_path = task_dir / f"sync_task_{workspace_name}.md"
        lines = [
            "# Sync Task — re-apply staged templates to project files",
            "",
            "**Merge rule:** `stage_all()` has already merged planner content into `CLAUDE.md` and executor content into `AGENTS.md` using owrap markers.",
            "For the files listed below: read each STAGED file and write its contents to the TARGET path.",
            "If TARGET exists, replace it entirely with STAGED (templates are authoritative; staging already substituted placeholders).",
            "Create parent directories as needed.",
            "",
            "## Files",
            "",
        ]
        for src, dst in targets:
            lines.append(f"- STAGED: `{src}`  →  TARGET: `{dst}`")
        lines += [
            "",
            "## Output",
            "",
            "List each file written with a one-line confirmation.",
        ]
        task_path.write_text("\n".join(lines) + "\n")
        return task_path
