import json
import shlex
from copy import deepcopy
from pathlib import Path


def _owrap_hook(hook: dict) -> bool:
    command = hook.get("command", "")
    if not isinstance(command, str):
        return False
    if hook.get("statusMessage") in {
        "Checking owrap permission", "Saving owrap context",
    }:
        return True
    if "#DO NOW" in command and "owrap refresh" in command:
        return True
    try:
        parts = shlex.split(command)
    except ValueError:
        return False
    # ctx-hook is the pre-rename name, still cleaned up
    return (
        len(parts) >= 2
        and Path(parts[0]).name == "owrap"
        and (
            parts[1] in {"p", "ctx-hook"}
            or parts[1:4] == ["ctx", "get", "hook"]
        )
    )


def merge_hooks(existing: dict, managed: dict) -> dict:
    """
    Replace owrap hooks while retaining other hooks and event settings.
    """
    if not isinstance(existing, dict) or not isinstance(managed, dict):
        raise ValueError("Hook configuration must be a JSON object")
    result = deepcopy(existing)
    for event, managed_groups in managed.items():
        groups = result.get(event, [])
        if not isinstance(groups, list) or not isinstance(managed_groups, list):
            raise ValueError(f"Invalid {event} hook groups")
        retained = []
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                retained.append(group)
                continue
            hooks = [hook for hook in group["hooks"] if not (
                isinstance(hook, dict) and _owrap_hook(hook)
            )]
            if hooks:
                retained.append({**group, "hooks": hooks})
        result[event] = retained + deepcopy(managed_groups)
    return result


def merge_claude_settings(existing_text: str, managed_text: str) -> str:
    """
    Merge owrap permissions and hooks into existing Claude settings.
    """
    existing = json.loads(existing_text) if existing_text.strip() else {}
    managed = json.loads(managed_text)
    if not isinstance(existing, dict) or not isinstance(managed, dict):
        raise ValueError("Claude settings must be a JSON object")
    result = deepcopy(existing)
    permissions = result.setdefault("permissions", {})
    if not isinstance(permissions, dict):
        raise ValueError("Claude permissions must be a JSON object")
    managed_permissions = managed.get("permissions", {})
    permissions.setdefault("defaultMode", managed_permissions.get("defaultMode"))
    allow = permissions.setdefault("allow", [])
    if not isinstance(allow, list):
        raise ValueError("Claude permissions.allow must be a JSON array")
    for rule in managed_permissions.get("allow", []):
        if rule not in allow:
            allow.append(rule)
    result["hooks"] = merge_hooks(
        result.get("hooks", {}), managed.get("hooks", {}),
    )
    return json.dumps(result, indent=2) + "\n"


def merge_codex_hooks(existing_text: str, managed_text: str) -> str:
    """
    Merge owrap hooks into existing Codex hook settings.
    """
    existing = json.loads(existing_text) if existing_text.strip() else {}
    managed = json.loads(managed_text)
    if not isinstance(existing, dict) or not isinstance(managed, dict):
        raise ValueError("Codex hook settings must be a JSON object")
    hooks = existing.get("hooks", {})
    managed_hooks = managed.get("hooks", {})
    if not isinstance(hooks, dict) or not isinstance(managed_hooks, dict):
        raise ValueError("Codex hooks must be a JSON object")
    result = deepcopy(existing)
    result["hooks"] = merge_hooks(hooks, managed_hooks)
    return json.dumps(result, indent=2) + "\n"


def remove_owrap_hooks(settings_text: str) -> str:
    """
    Remove older owrap hooks from Claude project settings.
    """
    data = json.loads(settings_text)
    if not isinstance(data, dict):
        raise ValueError("Claude settings must be a JSON object")
    hooks = data.get("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("Claude hooks must be a JSON object")
    cleaned = merge_hooks(hooks, {event: [] for event in hooks})
    if cleaned == hooks:
        return settings_text
    data["hooks"] = {event: groups for event, groups in cleaned.items() if groups}
    return json.dumps(data, indent=2) + "\n"
