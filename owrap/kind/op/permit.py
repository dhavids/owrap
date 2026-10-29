import fnmatch
import json
import sys
from pathlib import Path

from . import Op
from ...utils.session.resolver import owrap_sid_for_ccsid, owrap_sid_for_codex_session_id
from ...utils.paths import CONFIGS_DIR, _read_config, get_workspace_config
from ...utils.staging import stage_all

FLAGS = {"bypass-all": "permit_bypass_all"}
DEFAULT_FLAG = "bypass-all"


class Permit(Op):
    """
    Answer opencode's per-tool-call permission hook against a
    workspace's staged rules, or inspect/toggle a named permission
    flag. `do` is the hook itself -- it reads one tool-call payload
    as JSON from stdin and writes its allow/deny decision to stdout,
    the shape opencode invokes directly with no action word.
    """

    kind = "permit"

    usage = {
        "set": {
            "usage": "<on|off> | <name> <on|off>",
            "args": [
                ("on|off", f"shorthand for '{DEFAULT_FLAG} <on|off>'"),
                ("name", f"one of {', '.join(FLAGS)}"),
            ],
            "examples": ["on", "bypass-all off"],
        },
        "get": {
            "usage": "[<workspace>]",
            "args": [("workspace", "defaults to default_workspace")],
            "examples": ["", "myworkspace"],
        },
    }

    messages = {"set": "{message}", "get": "{message}"}


    # Public Methods

    def do(self, workspace: str = None) -> None:
        try:
            data = json.load(sys.stdin)
        except Exception:
            sys.exit(0)

        tool = data.get("tool_name", "")
        inp = data.get("tool_input", {})
        session_id = data.get("session_id", "")
        codex_session = bool(
            session_id and owrap_sid_for_codex_session_id(session_id)
        )
        claude_session = bool(session_id and owrap_sid_for_ccsid(session_id))
        is_codex = codex_session or (workspace is not None and not claude_session)
        event = (
            data.get("hook_event_name", "PreToolUse") if is_codex else "PreToolUse"
        )

        ws_name = workspace or _read_config().get("default_workspace", "")
        if workspace:
            ws_path = get_workspace_config(workspace).get("workspace")
            cwd = data.get("cwd")
            if not ws_path or not cwd or not Path(cwd).resolve().is_relative_to(
                Path(ws_path).expanduser().resolve()
            ):
                self._deny("Codex hook workspace does not match its staged rules.", event)
                return
        suffix = "_codex_permit.json" if is_codex else "_permit.json"
        permit_path = CONFIGS_DIR / f"{ws_name}{suffix}"
        if is_codex and not permit_path.exists():
            permit_path = CONFIGS_DIR / f"{ws_name}_permit.json"

        if not permit_path.exists():
            if workspace:
                self._deny(
                    f"No staged permit rules for '{ws_name}'; run `owrap sync`.", event,
                )
            sys.exit(0)

        permit = json.loads(permit_path.read_text())
        if isinstance(permit, dict) and permit.get("bypass_all"):
            self._allow(event, is_codex)
            return
        rules = permit.get("rules", permit) if isinstance(permit, dict) else permit
        orun_cmd = (
            permit.get("orun_cmd", "~/bin/orun") if isinstance(permit, dict)
            else "~/bin/orun"
        )
        if any(self._matches(rule, tool, inp) for rule in rules):
            self._allow(event, is_codex)
            return
        self._deny(self._denial_reason(tool, inp, orun_cmd), event)

    def set(self, first: str = None, second: str = None) -> None:
        """
        `set <on|off>` toggles `bypass-all`; `set <name> <on|off>`
        toggles any other flag in `FLAGS`.
        """
        if first is None:
            self._usage("set")
        name, state = (DEFAULT_FLAG, first) if second is None else (first, second)
        if name not in FLAGS:
            self._fail(f"unknown flag '{name}'. Valid: {', '.join(FLAGS)}")
        if state not in ("on", "off"):
            self._fail(f"expected 'on' or 'off', got '{state}'")

        ws_name = _read_config().get("default_workspace", "")
        cfg_path = CONFIGS_DIR / f"{ws_name}.json"
        if not cfg_path.exists():
            self._fail(f"no config file for workspace '{ws_name}'")

        cfg = json.loads(cfg_path.read_text())
        cfg[FLAGS[name]] = (state == "on")
        cfg_path.write_text(json.dumps(cfg, indent=2))
        stage_all(ws_name)

        if state == "on":
            message = (
                f"PERMIT {name.upper()}: now ON for '{ws_name}' — owrap permit will "
                f"auto-approve every Bash/Write/Edit call. Turn off with "
                f"`owrap permit set {name} off`."
            )
        else:
            message = f"PERMIT {name.upper()}: now off for '{ws_name}'."
        self._ok("set", message=message)

    def get(self, workspace: str = None) -> None:
        ws_name = workspace or _read_config().get("default_workspace", "")
        permit_path = CONFIGS_DIR / f"{ws_name}_permit.json"
        if not permit_path.exists():
            self._ok("get", message=f"No permit file staged for '{ws_name}' — run "
                                     f"`owrap sync`.")
            return
        permit = json.loads(permit_path.read_text())
        if permit.get("bypass_all"):
            message = (
                f"PERMIT BYPASS ALL: ON for '{ws_name}' — owrap permit auto-approves "
                f"every Bash/Write/Edit call, no rule matching. Turn off with "
                f"`owrap permit set bypass-all off`."
            )
        else:
            message = f"PERMIT BYPASS ALL: off for '{ws_name}' — normal rules apply."
        self._ok("get", message=message)


    # Private Methods

    def _matches(self, rule: str, tool: str, inp: dict) -> bool:
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

    def _denial_reason(self, tool: str, inp: dict, orun_cmd: str) -> str:
        if tool == "Bash":
            subject = inp.get("command", "")
            label = f"Bash({subject})" if subject else "Bash"
        elif tool in ("Write", "Edit", "Read"):
            subject = inp.get("file_path", "")
            label = f"{tool}({subject})" if subject else tool
        else:
            label = tool
        return (
            f"Blocked: {label}. Use {orun_cmd} --msg \"<instruction>\" for short "
            f"tasks, or write a task file and run {orun_cmd} for longer ones."
        )

    @staticmethod
    def _allow(event: str, is_codex: bool = False) -> None:
        if event == "PermissionRequest":
            output = {"hookEventName": event, "decision": {"behavior": "allow"}}
        elif is_codex:
            return
        else:
            output = {"hookEventName": event, "permissionDecision": "allow"}
        print(json.dumps({"hookSpecificOutput": output}))

    @staticmethod
    def _deny(reason: str, event: str = "PreToolUse") -> None:
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
        print(json.dumps({"hookSpecificOutput": output}))
