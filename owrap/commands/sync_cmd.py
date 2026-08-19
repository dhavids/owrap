import json
import sys
from pathlib import Path

from ..staging import stage_all, resolve_flags
from ..utils.paths import get_workspace_config, _read_config
from ..utils.session_resolver import resolve, _parse


class SyncRunner:
    """
    Re-stage templates and write planner files directly.
    """

    def run(self):
        workspace_name, sid = self._active_workspace()
        if not workspace_name:
            print("Error: no active session. Run `owrap start <name>` first.")
            sys.exit(1)
        config = get_workspace_config(workspace_name)
        if not config.get("workspace"):
            print(
                f"Error: ~/.owrap/configs/{workspace_name}.json "
                f"missing `workspace`. Run `owrap setup` first."
            )
            sys.exit(1)

        staged = stage_all(workspace_name)
        workspace = config["workspace"]
        research_root = config.get("research_root") or f"{workspace}/docs/research"

        flags = resolve_flags(config)
        self._sync_global_read_permission(bool(flags.get("OREAD")))

        # stage_all() already merged planner.md -> CLAUDE.md and
        # executor.md -> AGENTS.md; self.md -> docs/research/self.md

        staged_settings = staged / "settings.json"
        if staged_settings.exists():
            target_local = f"{workspace}/.claude/settings.local.json"
            Path(target_local).parent.mkdir(parents=True, exist_ok=True)
            Path(target_local).write_text(staged_settings.read_text())

            settings_json_path = Path(workspace) / ".claude" / "settings.json"
            if settings_json_path.exists():
                settings_json_path.write_text(staged_settings.read_text())

        print(f"staged: {staged}")
        print(f"workspace: {workspace}")
        print(f"research_root: {research_root}")
        print()
        if flags.get("OWRAP_ENABLED"):
            print("sync complete — reread CLAUDE.md if needed")
        else:
            print(
                "owrap has now been disabled — dispatch tooling "
                "unavailable, work directly."
            )
        sys.exit(0)

    def _active_workspace(self):
        """
        Read active workspace name from current session file.
        """
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

    def _sync_global_read_permission(self, oread: bool):
        """
        Keep ~/.claude/settings.json (global, user-level) Read(//**)
        rule in sync with oread.

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
