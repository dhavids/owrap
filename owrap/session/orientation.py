def print_orientation(session_id, research, url=None, plan_path=None, todo_path=None, input_path=None, context_path=None, area=None, memory_path=None, project_path=None, protocol_path=None):
    import shutil as _shutil
    import io as _io
    import re as _re
    import sys as _sys
    import textwrap as _tw
    from pathlib import Path as _Path
    _in_path = bool(_shutil.which("oread"))
    _buf = _io.StringIO()
    _orig_out = _sys.stdout
    _sys.stdout = _buf
    sep = "─" * 65
    r = research or "none"
    focus = ""
    plan_steps = []
    env_line = ""
    if context_path:
        _cp = _Path(context_path)
        if _cp.exists():
            _text = _cp.read_text()
            _m = _re.search(r"^## Focus\s*\n(.+?)(?=\n## |\Z)", _text, _re.DOTALL | _re.MULTILINE)
            if _m:
                focus = _m.group(1).strip()
            _m = _re.search(r"^## Active Plan\s*\n(.+?)(?=\n## |\Z)", _text, _re.DOTALL | _re.MULTILINE)
            if _m:
                plan_steps = _re.findall(r"^(?:\d+\. \[ \]|- \[ \])\s+(.+)$", _m.group(1), _re.MULTILINE)[:3]
            _m = _re.search(r"^## Environment\s*\n(.+?)(?=\n## |\Z)", _text, _re.DOTALL | _re.MULTILINE)
            if _m:
                for _line in _m.group(1).splitlines():
                    _line = _line.strip()
                    if _line and not _line.startswith("session:"):
                        env_line = _line
                        break
    print("=== OWRAP SESSION ===")
    server_str = f"   server: {url}" if url else ""
    print(f"  session: {session_id}   research: {r}{server_str}")
    print()
    print("You are the planner. Design plans, dispatch work, review results. Never write code or run commands directly.")
    print()
    print("KEY FILES")
    print(f"  plan    {plan_path}")
    print(f"  input   {input_path}")
    if area:
        print(f"  area    {area}")
    if memory_path:
        _area_tag = f"#{area}" if area else ""
        print(f"  memory  {memory_path}{_area_tag}")
    if project_path:
        _area_tag = f"#{area}" if area else ""
        print(f"  project {project_path}{_area_tag}")
    if protocol_path:
        print(f"  updr    {protocol_path}")
    if focus or context_path or plan_steps or env_line:
        print()
        print("FOCUS")
        if focus:
            for _chunk in _tw.wrap(focus, width=100):
                print(f"  {_chunk}")
        if context_path:
            print(f"  context: {context_path}")
        if plan_steps:
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
