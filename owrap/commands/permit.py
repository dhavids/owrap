import fnmatch
import json
import sys
from pathlib import Path


class PermitRunner:
    """
    Check staged permission rules for tool calls and approval requests.
    """

    def run(self, workspace_name=None):
        """
        Check a tool call against the workspace's staged permission rules.
        """
        try:
            data = json.load(sys.stdin)
        except Exception:
            sys.exit(0)

        tool = data.get("tool_name", "")
        inp = data.get("tool_input", {})
        session_id = data.get("session_id", "")
        from ..utils.session.resolver import (
            owrap_sid_for_ccsid, owrap_sid_for_codex_session_id,
        )
        codex_session = bool(
            session_id and owrap_sid_for_codex_session_id(session_id)
        )
        claude_session = bool(session_id and owrap_sid_for_ccsid(session_id))
        is_codex = codex_session or (workspace_name is not None and not claude_session)
        event = (
            data.get("hook_event_name", "PreToolUse")
            if is_codex else "PreToolUse"
        )

        from ..utils.paths import CONFIGS_DIR, _read_config, get_workspace_config
        ws_name = workspace_name or _read_config().get("default_workspace", "")
        if workspace_name:
            workspace = get_workspace_config(workspace_name).get("workspace")
            cwd = data.get("cwd")
            if not workspace or not cwd or not Path(cwd).resolve().is_relative_to(
                Path(workspace).expanduser().resolve()
            ):
                self._deny(
                    "Codex hook workspace does not match its staged rules.",
                    event,
                )
                return
        suffix = "_codex_permit.json" if is_codex else "_permit.json"
        permit_path = CONFIGS_DIR / f"{ws_name}{suffix}"
        if is_codex and not permit_path.exists():
            permit_path = CONFIGS_DIR / f"{ws_name}_permit.json"

        if not permit_path.exists():
            if workspace_name:
                self._deny(
                    f"No staged permit rules for '{ws_name}'; run `owrap sync`.",
                    event,
                )
            sys.exit(0)

        permit = json.loads(permit_path.read_text())
        if isinstance(permit, dict) and permit.get("bypass_all"):
            self._allow(event, is_codex)
            return
        rules = permit.get("rules", permit) if isinstance(permit, dict) else permit
        orun_cmd = (
            permit.get("orun_cmd", "~/bin/orun")
            if isinstance(permit, dict) else "~/bin/orun"
        )

        def matches(rule):
            if "(" not in rule:
                return rule == tool
            rtool, rest = rule.split("(", 1)
            if rtool != tool:
                return False
            pattern = rest.rstrip(")")
            if tool == "Bash":
                subject = inp.get("command", "")
            elif tool in ("Write", "Edit", "Read"):
                subject = inp.get("file_path", "")
            else:
                return True
            if fnmatch.fnmatch(subject, pattern):
                return True
            try:
                stem = pattern.split("*")[0]
                expanded = str(Path(stem).expanduser()) + ("*" if "*" in pattern else "")
                return fnmatch.fnmatch(subject, expanded)
            except Exception:
                return False

        if any(matches(r) for r in rules):
            self._allow(event, is_codex)
            return

        # Build a descriptive label for the denial
        if tool == "Bash":
            subject = inp.get("command", "")
            label = f"Bash({subject})" if subject else "Bash"
        elif tool in ("Write", "Edit", "Read"):
            subject = inp.get("file_path", "")
            label = f"{tool}({subject})" if subject else tool
        else:
            label = tool
        self._deny(
            f"Blocked: {label}. Use {orun_cmd} --msg "
            f"\"<instruction>\" for short tasks, or write a task file "
            f"and run {orun_cmd} for longer ones.",
            event,
        )

    @staticmethod
    def _allow(event, is_codex=False):
        if event == "PermissionRequest":
            output = {"hookEventName": event, "decision": {"behavior": "allow"}}
        elif is_codex:
            return
        else:
            output = {"hookEventName": event, "permissionDecision": "allow"}
        print(json.dumps({"hookSpecificOutput": output}))

    @staticmethod
    def _deny(reason, event="PreToolUse"):
        if event == "PermissionRequest":
            output = {
                "hookEventName": event,
                "decision": {"behavior": "deny", "message": reason},
            }
        else:
            output = {
                "hookEventName": event,
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        print(json.dumps({
            "hookSpecificOutput": output,
        }))


class PermitCmdRunner:
    """
    Inspect or toggle the permit auto-approve-all bypass for a workspace.
    """

    def run_status(self):
        """
        Print whether bypass_all is currently on for the active workspace.
        """
        ws_name, permit_path = self._resolve_permit_path()
        if not permit_path.exists():
            print(f"No permit file staged for '{ws_name}' — run `owrap sync`.")
            return
        permit = json.loads(permit_path.read_text())
        if permit.get("bypass_all"):
            print(
                f"PERMIT BYPASS ALL: ON for '{ws_name}' — owrap p auto-approves "
                f"every Bash/Write/Edit call, no rule matching. Turn off with "
                f"`owrap permit bypass-all off`."
            )
        else:
            print(f"PERMIT BYPASS ALL: off for '{ws_name}' — normal rules apply.")

    def run_bypass_all(self, state: str):
        """
        Set permit_bypass_all in the workspace config and re-stage permit.json.
        """
        if state not in ("on", "off"):
            print(f"ERROR: expected 'on' or 'off', got '{state}'")
            sys.exit(2)

        ws_name, _ = self._resolve_permit_path()
        from ..utils.paths import CONFIGS_DIR
        cfg_path = CONFIGS_DIR / f"{ws_name}.json"
        if not cfg_path.exists():
            print(f"ERROR: no config file for workspace '{ws_name}'")
            sys.exit(2)

        cfg = json.loads(cfg_path.read_text())
        cfg["permit_bypass_all"] = (state == "on")
        cfg_path.write_text(json.dumps(cfg, indent=2))

        from ..staging import stage_all
        stage_all(ws_name)

        if state == "on":
            print(
                f"PERMIT BYPASS ALL: now ON for '{ws_name}' — owrap p will "
                f"auto-approve every Bash/Write/Edit call. Turn off with "
                f"`owrap permit bypass-all off`."
            )
        else:
            print(f"PERMIT BYPASS ALL: now off for '{ws_name}'.")


    # Private Methods

    def _resolve_permit_path(self):
        """
        Return (workspace_name, permit_path) for the active workspace.
        """
        from ..utils.paths import CONFIGS_DIR, _read_config
        config = _read_config()
        ws_name = config.get("default_workspace", "")
        return ws_name, CONFIGS_DIR / f"{ws_name}_permit.json"
