import pytest

from owrap.runner import _build_parser

# One representative invocation per subcommand (every entry in
# _COMMAND_HANDLERS, plus the 3 inline-dispatched commands p/permit/set),
# pinning argparse's exact parsed-namespace behavior as a regression check
# against the declarative schema it's built from.
REPRESENTATIVE_CASES = [
    (["start", "myproj", "sub1"], {
        "allow_all": False, "branch_parent": None, "branch_ref": None,
        "branch_repository": None, "command": "start", "project": None,
        "project_name": "myproj", "repo_ids": None, "repository": None,
        "session_file": None, "session_id": None, "shell_pid": None,
        "subproject": None, "subproject_name": "sub1"
    }),
    (["start", "--repository", "repo1"], {
        "allow_all": False, "branch_parent": None, "branch_ref": None,
        "branch_repository": None, "command": "start", "project": None,
        "project_name": None, "repo_ids": None, "repository": "repo1",
        "session_file": None, "session_id": None, "shell_pid": None,
        "subproject": None, "subproject_name": None
    }),
    (["branch", "child1", "--ref", "refname"], {
        "allow_all": False, "apply": False, "command": "branch", "name": "child1",
        "ref": "refname", "repo": None, "session": None
    }),
    (["stop", "sid1", "--force"], {
        "allow_all": False, "command": "stop", "force": True, "session_file": None,
        "session_id": None, "target": "sid1"
    }),
    (["end", "sid1"], {
        "allow_all": False, "command": "end", "session_file": None, "session_id": None,
        "target": "sid1"
    }),
    (["refresh", "proj1", "sub1"], {
        "allow_all": False, "command": "refresh", "project_name": "proj1",
        "session_file": None, "session_id": None, "shell_pid": None,
        "subproject_name": "sub1"
    }),
    (["attach", "sid1"], {
        "allow_all": False, "command": "attach", "shell_pid": None,
        "target_session_id": "sid1"
    }),
    (["detach"], {
        "allow_all": False, "command": "detach"
    }),
    (["todo", "proj1", "text here"], {
        "allow_all": False, "arg2": "text here", "arg3": None, "arg4": None,
        "command": "todo", "target": "proj1"
    }),
    (["todo", "update", "proj1", "2", "text"], {
        "allow_all": False, "arg2": "proj1", "arg3": "2", "arg4": "text",
        "command": "todo", "target": "update"
    }),
    (["decide", "proj1", "text"], {
        "allow_all": False, "command": "decide", "target": "proj1", "text": "text"
    }),
    (["main"], {
        "allow_all": False, "command": "main"
    }),
    (["sub", "subname", "-f"], {
        "allow_all": False, "command": "sub", "force": True, "name": "subname"
    }),
    (["subs"], {
        "allow_all": False, "command": "subs"
    }),
    (["restart", "proj1"], {
        "allow_all": False, "command": "restart", "force": False,
        "project_name": "proj1",
        "session_file": None, "session_id": None, "shell_pid": None
    }),
    (["setup", "/path", "--planner", "claude", "--planner", "codex"], {
        "allow_all": None, "command": "setup", "docs_root": None, "executors": None,
        "name": None, "oread": None, "path": "/path", "planners": ["claude", "codex"],
        "workspace": None
    }),
    (["sync"], {
        "allow_all": False, "command": "sync"
    }),
    (["read", "-f", "a.py", "b.py", "-g", "pattern"], {
        "allow_all": False, "command": "read", "debug": False, "details": None,
        "files": ["a.py", "b.py"], "grep": "pattern", "id": None, "list_styles": False,
        "log_time": False, "prompt_style": None, "summarise": False, "timeout": None,
        "verbose": False
    }),
    (["run", "--msg", "hello", "-t", "30"], {
        "add_context": False, "allow_all": False, "command": "run", "debug": False,
        "disablewd": False, "id": None, "input": None, "log_time": False,
        "model": None, "msg": "hello", "timeout": 30
    }),
    (["exec", "--model", "gpt"], {
        "allow_all": False, "command": "exec", "debug": False, "disablewd": False,
        "log_time": False, "model": "gpt", "timeout": None
    }),
    (["work", "--model", "gpt"], {
        "allow_all": False, "command": "work", "debug": False, "disablewd": False,
        "log_time": False, "model": "gpt", "timeout": None
    }),
    (["stat", "sid1"], {
        "allow_all": False, "command": "stat", "filter": "sid1"
    }),
    (["cleanup", "trash"], {
        "allow_all": False, "command": "cleanup", "session_id": "trash"
    }),
    (["restore", "trash", "sid1"], {
        "allow_all": False, "command": "restore", "session_id": "sid1", "what": "trash"
    }),
    (["agent", "do this"], {
        "allow_all": False, "clear": False, "command": "agent", "data": "do this",
        "debug": False, "disablewd": False, "id": None, "log_time": False,
        "model": None, "timeout": None
    }),
    (["abort", "task1"], {
        "allow_all": False, "command": "abort", "session": None, "target": "task1"
    }),
    (["agents", "clear"], {
        "action": "clear", "allow_all": False, "command": "agents"
    }),
    (["killservers", "--session", "sid1"], {
        "allow_all": False, "command": "killservers", "session": "sid1"
    }),
    (["f", "/path/to.md"], {
        "allow_all": False, "command": "f", "path": "/path/to.md"
    }),
    (["spawn", "childname"], {
        "allow_all": False, "child": "childname", "command": "spawn"
    }),
    (["temp", "name1"], {
        "allow_all": False, "command": "temp", "name": "name1"
    }),
    (["collapse", "--session", "sid1", "--apply"], {
        "allow_all": False, "apply": True, "command": "collapse", "session": "sid1"
    }),
    (["update-home", "/new/path", "--migrate"], {
        "allow_all": False, "command": "update-home", "dry_run": False,
        "migrate": True, "path": "/new/path"
    }),
    (["ctx-hook"], {
        "allow_all": False, "command": "ctx-hook"
    }),
    (["ctx-worker", "--input", "/path.json"], {
        "allow_all": False, "command": "ctx-worker", "input": "/path.json"
    }),
    (["ctx"], {
        "allow_all": False, "command": "ctx", "action": None, "error": None,
    }),
    (["ctx", "done", "--error", "oops"], {
        "allow_all": False, "command": "ctx", "action": "done", "error": "oops",
    }),
    (["updr", "sub1", "--ctx"], {
        "allow_all": False, "command": "updr", "ctx": True, "subproject": "sub1",
        "error": None,
    }),
    (["updr", "done", "--error", "oops"], {
        "allow_all": False, "command": "updr", "ctx": False,
        "subproject": "done", "error": "oops",
    }),
    (["ctx-template", "sub1"], {
        "allow_all": False, "command": "ctx-template", "subproject": "sub1"
    }),
    (["touched", "a.py", "b.py", "--note", "n"], {
        "allow_all": False, "command": "touched", "note": "n", "paths": ["a.py", "b.py"]
    }),
    (["backup", "target1"], {
        "allow_all": False, "command": "backup", "target": "target1"
    }),
    (["retrieve", "target1", "2026"], {
        "allow_all": False, "command": "retrieve", "target": "target1",
        "timestamp": "2026"
    }),
    (["delete", "backup", "target1", "all"], {
        "allow_all": False, "command": "delete", "target": "target1", "what": "backup",
        "which": "all"
    }),
    (["rename", "project", "old1", "new1"], {
        "allow_all": False, "arg1": "old1", "arg2": "new1", "arg3": None,
        "command": "rename", "kind": "project"
    }),
    (["update", "subproject", "proj1", "old1", "new1"], {
        "allow_all": False, "arg1": "proj1", "arg2": "old1", "arg3": "new1",
        "command": "update", "kind": "subproject"
    }),
    (["get", "project"], {
        "allow_all": False, "ccsid": None, "command": "get", "count": 5, "ev": None,
        "head": 5, "id": None, "kind": None, "session": None, "sid": None, "tail": 5,
        "what": "project"
    }),
    (["get", "output", "msg", "--id", "x"], {
        "allow_all": False, "ccsid": None, "command": "get", "count": 5, "ev": None,
        "head": 5, "id": "x", "kind": "msg", "session": None, "sid": None, "tail": 5,
        "what": "output"
    }),
    (["get", "history", "7"], {
        "allow_all": False, "ccsid": None, "command": "get", "count": 5, "ev": None,
        "head": 5, "id": None, "kind": "7", "session": None, "sid": None, "tail": 5,
        "what": "history"
    }),
    (["daemon"], {
        "allow_all": False, "command": "daemon", "action": None
    }),
    (["daemon", "restart"], {
        "allow_all": False, "command": "daemon", "action": "restart"
    }),
    (["p", "--workspace", "ws1"], {
        "allow_all": False, "command": "p", "workspace": "ws1"
    }),
    (["permit", "bypass-all", "on"], {
        "action": "bypass-all", "allow_all": False, "command": "permit", "state": "on"
    }),
    (["set", "model", "runner", "query text"], {
        "allow_all": False, "command": "set", "query": "query text",
        "set_target": "model", "slot": "runner", "workspace": None
    }),
    (["wait", "msg", "id1", "--timeout", "30"], {
        "allow_all": False, "command": "wait", "id": "id1", "session": None,
        "timeout": 30, "type": "msg"
    }),
]

_CASE_IDS = [" ".join(argv) for argv, _ in REPRESENTATIVE_CASES]


@pytest.mark.parametrize("argv,expected", REPRESENTATIVE_CASES, ids=_CASE_IDS)
def test_representative_command_parses_to_expected_namespace(argv, expected):
    parser = _build_parser()
    args = parser.parse_args(argv)
    assert vars(args) == expected


def test_start_project_and_repository_are_mutually_exclusive():
    parser = _build_parser()
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["start", "--project", "a", "--repository", "b"])
    assert exc_info.value.code == 2


def test_top_level_allow_all_flag_applies_to_any_command():
    parser = _build_parser()
    args = parser.parse_args(["-a", "detach"])
    assert args.allow_all is True
    assert args.command == "detach"


def test_every_handled_command_has_a_representative_case():
    from owrap.runner import _COMMAND_HANDLERS
    covered = {argv[0] for argv, _ in REPRESENTATIVE_CASES}
    missing = set(_COMMAND_HANDLERS) - covered
    assert not missing


def test_unknown_command_exits_nonzero():
    parser = _build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["not-a-real-command"])
