import json
import os
import subprocess
import sys
from pathlib import Path

from ..staging import stage_all, resolve_flags
from ..utils.paths import get_workspace_config, RUNTIME_HOME, _read_config
from ..utils.session_resolver import resolve, _parse, session_file as _sf


class SyncRunner:
    """Re-stage templates and dispatch sync_task.md via orun to write planner files."""

    def run(self):
        workspace_name, sid = self._active_workspace()
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

        flags = resolve_flags(config)
        self._sync_global_read_permission(bool(flags.get("OREAD")))

        # stage_all() already merged planner.md → CLAUDE.md and executor.md → AGENTS.md
        targets = [
            (staged / "self.md",       f"{research_root}/self.md"),
            (staged / "settings.json", f"{workspace}/.claude/settings.local.json"),
        ]
        settings_json_path = Path(workspace) / ".claude" / "settings.json"
        if settings_json_path.exists():
            targets.append((staged / "settings.json", str(settings_json_path)))

        task_path = self._write_sync_task(targets, sid)
        print(f"sync_task written: {task_path}")
        print(f"staged: {staged}")
        print(f"workspace: {workspace}")
        print(f"research_root: {research_root}")
        print()
        if flags.get("OWRAP_ENABLED"):
            print(f"Next: ~/bin/orun --input {task_path}")
        else:
            print("owrap has now been disabled — dispatch tooling unavailable, work directly.")
        sys.exit(0)

    def _active_workspace(self):
        """Read active workspace name from current session file."""
        session_id, session_path, source = resolve(mode="refresh")
        if session_id is None:
            return (None, None)
        data = _parse(session_path)
        workspace_name = data.get("workspace")
        if not workspace_name:
            workspace_name = _read_config().get("default_workspace", "")
        if not workspace_name:
            return (None, None)
        return workspace_name, session_id

    def _write_sync_task(self, targets, sid):
        task_dir = RUNTIME_HOME / 'docs' / 'sessions' / sid / 'run'
        task_dir.mkdir(parents=True, exist_ok=True)
        task_path = task_dir / 'input_sync.md'
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

    def _sync_global_read_permission(self, oread: bool):
        """Keep ~/.claude/settings.json (global, user-level) Read(//**) rule in sync with oread.

        Claude Code's project-level settings.local.json/settings.json permission
        rules do not apply to paths outside the workspace root, regardless of
        additionalDirectories or rule syntax. Only a global user-level rule
        works for out-of-workspace reads. When oread=false, direct Read is
        intended, so we ensure this rule is present. When oread=true, direct
        Read should go through the oread tool instead, so we remove it if
        present. Never clobbers other content already in the global file.
        """
        global_settings_path = Path.home() / ".claude" / "settings.json"
        try:
            if global_settings_path.exists() and global_settings_path.stat().st_size > 0:
                data = json.loads(global_settings_path.read_text())
            else:
                data = {}
        except Exception:
            return
        if not isinstance(data, dict):
            return
        permissions = data.setdefault("permissions", {})
        allow = permissions.setdefault("allow", [])
        changed = False
        if oread:
            if "Read(//**)" in allow:
                allow.remove("Read(//**)")
                changed = True
        else:
            if "Read(//**)" not in allow:
                allow.append("Read(//**)")
                changed = True
        if changed:
            global_settings_path.parent.mkdir(parents=True, exist_ok=True)
            global_settings_path.write_text(json.dumps(data, indent=2) + "\n")
            action = "Removed" if oread else "Merged"
            print(f"{action} Read(//**) in global {global_settings_path}")
