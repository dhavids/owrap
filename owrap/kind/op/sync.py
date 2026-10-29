import json
from pathlib import Path

from . import Op
from ...utils.harness import (
    merge_claude_settings, merge_codex_hooks, remove_owrap_hooks,
)
from ...utils.memory.names import name_notices
from ...utils.paths import _read_config, get_workspace_config
from ...utils.staging import resolve_flags, resolve_role_files, stage_all
from ...utils.session.resolver import _parse as _parse_session, resolve as resolve_session


class Sync(Op):
    """
    Re-stage the active session's workspace configuration and
    install its agent settings and hooks.
    """

    kind = "sync"

    usage = {
        "do": {
            "usage": "", "args": [], "examples": [""],
            "purpose": "Stage and merge workspace instructions",
            "group": "record",
        },
    }

    messages = {"do": "{message}"}


    # Public Methods

    def do(self) -> None:
        workspace_name = self._active_workspace()
        if not workspace_name:
            self._fail("no active session. Run `owrap session start <name>` first.")
        config = get_workspace_config(workspace_name)
        if not config.get("workspace"):
            self._fail(
                f"~/.owrap/configs/{workspace_name}.json missing `workspace`. "
                f"Run `owrap setup` first."
            )

        staged = stage_all(workspace_name)
        workspace = config["workspace"]
        docs_root = config.get("docs_root") or f"{workspace}/docs/research"

        flags = resolve_flags(config)
        self._sync_global_read_permission(bool(flags.get("OREAD")))

        workspace_path = Path(workspace)
        for harness, install in (
            ("claude", self._sync_claude), ("codex", self._sync_codex),
        ):
            harness_dir = staged / harness
            if harness_dir.is_dir():
                install(workspace_path, harness_dir)

        lines = [
            f"staged: {staged}", f"workspace: {workspace}",
            f"docs_root: {docs_root}", "",
        ]
        lines += self._name_notices(workspace_name)
        if flags.get("RUNNER_ENABLED"):
            planner_files = resolve_role_files(config)["planner"]
            lines.append(f"sync complete — reread {', '.join(planner_files)} if needed")
        else:
            lines.append("owrap runner has now been disabled — work directly.")
        self._ok("do", message="\n".join(lines))


    # Private Methods

    def _name_notices(self, workspace_name: str) -> list:
        """
        Warnings for project/subproject names that are reserved or
        used twice; never fails the sync.
        """
        try:
            notices = name_notices(workspace_name)
        except Exception:
            return []
        return [f"⚠ {notice}" for notice in notices] + ([""] if notices else [])

    def _active_workspace(self) -> str | None:
        session_id, session_path, source = resolve_session(mode="refresh")
        if session_id is None:
            return None
        data = _parse_session(session_path)
        workspace_name = (
            data.get("workspace") or _read_config().get("default_workspace", "")
        )
        return workspace_name or None

    def _sync_global_read_permission(self, oread: bool) -> None:
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

    def _sync_claude(self, workspace: Path, staged: Path) -> None:
        staged_settings = staged / "settings.json"
        if not staged_settings.exists():
            return
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

    def _sync_codex(self, workspace: Path, staged: Path) -> None:
        staged_codex_hooks = staged / "hooks.json"
        if not staged_codex_hooks.exists():
            return
        target_codex_hooks = workspace / ".codex" / "hooks.json"
        target_codex_hooks.parent.mkdir(parents=True, exist_ok=True)
        current = (
            target_codex_hooks.read_text() if target_codex_hooks.exists() else "{}"
        )
        target_codex_hooks.write_text(
            merge_codex_hooks(current, staged_codex_hooks.read_text()),
        )
