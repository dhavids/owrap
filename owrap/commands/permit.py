import fnmatch
import json
import sys
from pathlib import Path


class PermitRunner:
    """PreToolUse hook: reads staged permit.json and returns allow/deny decision."""

    def run(self):
        try:
            data = json.load(sys.stdin)
        except Exception:
            sys.exit(0)

        tool = data.get("tool_name", "")
        inp = data.get("tool_input", {})

        from ..utils.paths import CONFIGS_DIR, _read_config
        config = _read_config()
        ws_name = config.get("default_workspace", "")
        permit_path = CONFIGS_DIR / f"{ws_name}_permit.json"

        if not permit_path.exists():
            sys.exit(0)

        permit = json.loads(permit_path.read_text())
        if isinstance(permit, dict) and permit.get("allow_all"):
            print(json.dumps({
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "allow",
                }
            }))
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
            print(json.dumps({
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "allow",
                }
            }))
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
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": (
                    f"Blocked: {label}. Use {orun_cmd} --msg "
                    f"\"<instruction>\" for short tasks, or write a task file "
                    f"and run {orun_cmd} for longer ones."
                )
            }
        }))
