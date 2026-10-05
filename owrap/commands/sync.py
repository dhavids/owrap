import json
import sys
from pathlib import Path

from ..utils.harness import (
    merge_claude_settings, merge_codex_hooks, remove_owrap_hooks,
)
from ..staging import stage_all, resolve_flags, resolve_role_files
from ..utils.paths import get_workspace_config, _read_config
from ..utils.session.resolver import resolve, _parse


class SyncRunner:
    """
    Stage workspace configuration and sync agent settings.
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
        docs_root = (
            config.get("docs_root") or config.get("research_root")
            or f"{workspace}/docs/research"
        )

        flags = resolve_flags(config)
        self._sync_global_read_permission(bool(flags.get("OREAD")))

        workspace_path = Path(workspace)
        for harness, install in (
            ("claude", self._sync_claude),
            ("codex", self._sync_codex),
        ):
            harness_dir = staged / harness
            if harness_dir.is_dir():
                install(workspace_path, harness_dir)

        print(f"staged: {staged}")
        print(f"workspace: {workspace}")
        print(f"docs_root: {docs_root}")
        print()
        if flags.get("RUNNER_ENABLED"):
            planner_files = resolve_role_files(config)["planner"]
            print(f"sync complete — reread {', '.join(planner_files)} if needed")
        else:
            print("owrap runner has now been disabled — work directly.")
        sys.exit(0)

    def _sync_claude(self, workspace: Path, staged: Path):
        """
        Install Claude settings while keeping user settings.
        """
        staged_settings = staged / "settings.json"
        if staged_settings.exists():
            local_path = workspace / ".claude" / "settings.local.json"
            local_path.parent.mkdir(parents=True, exist_ok=True)
            managed_settings = staged_settings.read_text()
            current = local_path.read_text() if local_path.exists() else "{}"
            local_path.write_text(merge_claude_settings(current, managed_settings))

            settings_json_path = workspace / ".claude" / "settings.json"
            if settings_json_path.exists():
                current = settings_json_path.read_text()
                cleaned = remove_owrap_hooks(current)
                if cleaned != current:
                    settings_json_path.write_text(cleaned)

    def _sync_codex(self, workspace: Path, staged: Path):
        """
        Install Codex hooks from the staged harness directory.
        """
        staged_codex_hooks = staged / "hooks.json"
        if staged_codex_hooks.exists():
            target_codex_hooks = workspace / ".codex" / "hooks.json"
            target_codex_hooks.parent.mkdir(parents=True, exist_ok=True)
            current = (
                target_codex_hooks.read_text()
                if target_codex_hooks.exists()
                else "{}"
            )
            target_codex_hooks.write_text(merge_codex_hooks(
                current, staged_codex_hooks.read_text(),
            ))

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
