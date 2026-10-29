import io as _io
import json as _json
import re as _re
import shutil as _shutil
import sys as _sys
import textwrap as _tw
from pathlib import Path as _Path


def _name_notices(target) -> list:
    """
    Warnings for this target's own project/subproject names, if they
    are reserved or used twice; never fails the banner.
    """
    if target.kind != "project":
        return []
    try:
        from ..kind.record.identity import current_workspace
        from ..utils.memory.names import name_notices

        ids = tuple(i for i in (target.project_id, target.subproject_id) if i)
        return name_notices(current_workspace(), ids)
    except Exception:
        return []


def print_orientation(
    session_id, url=None, plan_path=None,
    input_path=None, context_path=None,
    memory_path=None, project_path=None,
    attach=False, runner_enabled=True, target=None,
):
    """
    Print the session orientation banner: server URL, plan/context
    paths, and memory/project links.
    """
    _in_path = bool(_shutil.which("oread"))
    _buf = _io.StringIO()
    _orig_out = _sys.stdout
    _sys.stdout = _buf
    sep = "─" * 65
    focus = ""
    plan_steps = []
    env_line = ""
    ctx_status = None
    if session_id and context_path:
        _state_path = _Path(context_path).parent / "ctx_state.json"
        if _state_path.exists():
            try:
                ctx_status = (
                    _json.loads(_state_path.read_text())
                    .get("ctx", {}).get("status")
                )
            except (_json.JSONDecodeError, OSError):
                pass
    if context_path:
        _cp = _Path(context_path)
        if _cp.exists():
            _text = _cp.read_text()
            _m = _re.search(
                r"^## Focus\s*\n(.+?)(?=\n## |\Z)",
                _text, _re.DOTALL | _re.MULTILINE,
            )
            if _m:
                focus = _m.group(1).strip()
            _m = _re.search(
                r"^## Active Plan\s*\n(.+?)(?=\n## |\Z)",
                _text, _re.DOTALL | _re.MULTILINE,
            )
            if _m:
                plan_steps = _re.findall(
                    r"^(?:\d+\. \[ \]|- \[ \])\s+(.+)$",
                    _m.group(1), _re.MULTILINE,
                )[:3]
            _m = _re.search(
                r"^## Environment\s*\n(.+?)(?=\n## |\Z)",
                _text, _re.DOTALL | _re.MULTILINE,
            )
            if _m:
                for _line in _m.group(1).splitlines():
                    _line = _line.strip()
                    if _line and not _line.startswith("session:"):
                        env_line = _line
                        break
    print("=== OWRAP SESSION ===")
    server_str = f"   server: {url}" if url else ""
    print(f"  session: {session_id}{server_str}")
    if target:
        if target.kind == "project":
            scope = target.subproject_id or "main"
            print(f"  project: {target.project_id}   subproject: {scope}")
        else:
            print(f"  repository: {target.repository_ids[0]}")
        for notice in _name_notices(target):
            print(f"  ⚠ {notice}")
        if target.high_risk:
            print(
                "  ⚠ this target is marked high-risk — context auto-dispatch "
                "is disabled; run `owrap ctx get template`, update the files "
                "by hand, then `owrap ctx done`",
            )
    if ctx_status in ("pending", "failed"):
        from ..ctx.dispatch import read_opencode_status_detail
        detail = read_opencode_status_detail()
        if detail["status"] == "down":
            reason = f" ({detail['reason']})" if detail["reason"] else ""
            print(
                f"  ⚠ last context-manager dispatch: {ctx_status} — "
                f"opencode is down{reason}; run `owrap ctx get template`, "
                f"update the files by hand, then `owrap ctx done`",
            )
        else:
            print(
                f"  ⚠ last context-manager dispatch: {ctx_status} — "
                f"run `owrap ctx`/`owrap updr` again if this is stale",
            )
    print()
    if runner_enabled:
        print(
            "You are the planner. Design plans, dispatch work, "
            "review results. Never write code or run commands "
            "directly.",
        )
    else:
        print(
            "You are the planner. The owrap runner is currently "
            "disabled — work directly: read files, write code, "
            "and run commands yourself as needed.",
        )
    print()
    _gi_path = None
    if session_id:
        try:
            from ..utils.paths import resolve_general_instruction_path as _rgip
            _gi_path = _rgip(session_id)
        except Exception:
            pass
    _targets_owrap = bool(
        target and target.kind == "project" and target.project_id == "owrap",
    )
    _self_path = None
    if _targets_owrap:
        from ..utils.paths import get_self_path as _gsp
        _self_path = _gsp()
    if _gi_path or (context_path and attach) or _self_path:
        print("RELOAD")
        if _gi_path:
            print(f"  {_gi_path} — read this file now before continuing.")
        if context_path and attach:
            print(
                f"  {context_path} — also re-read this file "
                f"for current session context.",
            )
        if _self_path:
            print(
                f"  {_self_path} — self-referential session (project: "
                f"owrap); re-read this file too.",
            )
    print()
    _fallback_note = ""
    if _targets_owrap:
        from ..utils.paths import FALLBACK_PLAN, FALLBACK_TASK
        plan_path = FALLBACK_PLAN
        input_path = FALLBACK_TASK
        if runner_enabled:
            _fallback_note = "  (project=owrap: dispatch via `owrap f <path>`)"
    print("KEY FILES")
    if runner_enabled:
        print(f"  plan    {plan_path}{_fallback_note}")
        print(f"  input   {input_path}{_fallback_note}")
    if target:
        if target.project_path:
            print(f"  goals   {target.project_path}#Goals")
            print(f"  project {target.project_path}")
        for repo_id, repo_path in zip(
            target.repository_ids, target.repository_paths,
        ):
            print(f"  repo    {repo_id}: {repo_path}")
    if memory_path and not target:
        print(f"  memory  {memory_path}")
    if project_path and not target:
        print(f"  project {project_path}")
    if focus or context_path or plan_steps or env_line:
        print()
        print("FOCUS")
        if focus:
            for _chunk in _tw.wrap(focus, width=100):
                print(f"  {_chunk}")
        if context_path:
            print(f"  context: {context_path}")
        if plan_steps and runner_enabled:
            print()
            print("PLAN")
            for _i, _step in enumerate(plan_steps, 1):
                _truncated = _step[:80]
                print(f"  {_i}. [ ] {_truncated}")
        if env_line:
            print()
            print("ENV")
            print(f"  {env_line}")
    print()
    print(sep)
    _sys.stdout = _orig_out
    _out = _buf.getvalue()
    if not _in_path:
        for _cmd in ("oread", "orun", "oexec", "owrap", "owait"):
            _out = _re.sub(rf'\b{_cmd}\b', f'~/bin/{_cmd}', _out)
    _sys.stdout.write(_out)
