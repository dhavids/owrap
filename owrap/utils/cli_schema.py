"""
Declarative schema for owrap's subcommand parsers, built by `_build_parser()`
in `runner.py`.

Each entry is one subcommand: `name` (and optional `aliases`/`help`) plus an
`args` list of argparse.add_argument() calls, each given as a dict whose
`flags` key is the positional list of names/option-strings and whose other
keys are passed straight through as add_argument() kwargs. An `args` entry
with a `group` key joins a mutually-exclusive group scoped to that command,
keyed by the group name. A command with a `subparsers` key (only "set" uses
this) gets one more level of nested subcommands, in the same shape.
"""

# Flag specs reused as-is or with overrides across several subcommands.
_DEBUG = {"flags": ["--debug"], "action": "store_true", "help": "Enable debug logging"}
_LOG_TIME = {
    "flags": ["--log-time"], "action": "store_true",
    "help": "Show the [timing] block (debugging/tests only)",
}
_MODEL = {
    "flags": ["--model", "-m"], "type": str, "default": None,
    "help": "Model override",
}
_DISABLEWD = {
    "flags": ["--disablewd"], "action": "store_true", "default": False,
    "help": "Disable stall/no-output watchdog; hard timeout still applies",
}
_APPLY = {"flags": ["--apply"], "action": "store_true"}
_SHELL_PID = {"flags": ["--shell-pid"], "type": int, "default": None, "help": "Shell PID"}
_SESSION_FILE = {
    "flags": ["--session-file"], "type": str, "default": None,
    "help": "Session file path",
}
_SESSION_ID = {"flags": ["-i", "--session-id"], "type": str, "default": None}
_TIMEOUT = {"flags": ["-t", "--timeout"], "type": int, "default": None}
_SESSION = {"flags": ["--session"], "type": str, "default": None}


def flag(base, **overrides):
    """
    Return a copy of a shared flag spec with keyword overrides applied.
    """
    spec = dict(base)
    spec.update(overrides)
    return spec


SUBCOMMANDS = [
    {
        "name": "start", "help": "Start an owrap session",
        "args": [
            {"flags": ["project_name"], "nargs": "?", "default": None,
             "help": "Project ID: attach if it exists, create if not "
                     "(use --repository for a repository-only session)"},
            _SHELL_PID,
            _SESSION_FILE,
            flag(_SESSION_ID,
                 help="Session ID: attach if exists, create with this ID if not"),
            {"flags": ["subproject_name"], "nargs": "?", "default": None,
             "help": "Subproject ID within the project, created if new"},
            {"flags": ["--project", "--proj"], "dest": "project",
             "group": "target", "help": "Project ID for the session"},
            {"flags": ["--repository", "--repo"], "dest": "repository",
             "group": "target",
             "help": "Repository ID for a repository-only session"},
            {"flags": ["--subproject", "--sub", "--subs"], "dest": "subproject",
             "help": "Subproject ID within --project"},
            {"flags": ["--repo-id", "--repos"], "dest": "repo_ids",
             "action": "append", "help": "Associated repository ID (repeatable)"},
            {"flags": ["--branch-parent"],
             "help": "Explicit parent ID for a branch subproject"},
            {"flags": ["--branch-repository"],
             "help": "Repository ID containing the branch"},
            {"flags": ["--branch-ref"], "help": "Git ref for the branch"},
        ],
    },
    {
        "name": "branch",
        "help": "Start a child session with Git worktrees, or merge its code",
        "args": [
            {"flags": ["name"], "nargs": "?", "default": None},
            {"flags": ["--ref"], "help": "Git branch ref for a new session"},
            {"flags": ["--session"], "help": "Branch session ID for merge"},
            {"flags": ["--repo"], "help": "Repository ID for merge"},
            _APPLY,
        ],
    },
    {
        "name": "stop", "help": "Stop an owrap session",
        "args": [
            {"flags": ["target"], "nargs": "?", "default": None,
             "help": "Session ID prefix or research name to stop "
                     "(alias for -i/--session-id)"},
            flag(_SESSION_ID, help="Session ID or research name to stop "
                 "(alias for positional target)"),
            _SESSION_FILE,
            {"flags": ["--force"], "action": "store_true", "default": False,
             "help": "Kill server and clear all sessions even if others are active"},
        ],
    },
    {
        "name": "end", "help": "End this session only (server keeps running)",
        "args": [
            {"flags": ["target"], "nargs": "?", "default": None,
             "help": "Session ID prefix or research name to end "
                     "(alias for -i/--session-id)"},
            flag(_SESSION_ID, help="Session ID or research name to end "
                 "(alias for positional target)"),
            flag(_SESSION_FILE, help=None),
        ],
    },
    {
        "name": "refresh", "help": "Refresh an owrap session",
        "args": [
            {"flags": ["project_name"], "nargs": "?", "default": None,
             "help": "Project ID to redirect this session to"},
            _SHELL_PID,
            _SESSION_FILE,
            flag(_SESSION_ID, help="Session ID to refresh (skips env resolution)"),
            {"flags": ["subproject_name"], "nargs": "?", "default": None,
             "help": "Subproject ID within project_name"},
        ],
    },
    {
        "name": "attach", "help": "Bind an existing session to this Claude window",
        "args": [
            {"flags": ["target_session_id"], "help": "Session ID to attach to"},
            flag(_SHELL_PID, help="Shell PID (ignored)"),
        ],
    },
    {"name": "detach", "help": "Release this window's attachment to its session"},
    {
        "name": "todo",
        "help": "Add, insert, update, mark done, or clear todo entries for a project",
        "args": [
            {"flags": ["target"],
             "help": "Session id, project/repository name, 'clear' to clear "
                     "done items, 'done' to mark one item done, or 'update' "
                     "to replace an item in place"},
            {"flags": ["arg2"], "nargs": "?", "default": None,
             "help": "Todo text, position, or (after 'clear'/'done'/'update') "
                     "the target"},
            {"flags": ["arg3"], "nargs": "?", "default": None,
             "help": "Todo text when arg2 is a position, (after 'done') the "
                     "selector, or (after 'update') the position"},
            {"flags": ["arg4"], "nargs": "?", "default": None,
             "help": "Todo text when arg3 is a position (after 'update')"},
        ],
    },
    {
        "name": "decide",
        "help": "Add a timestamped decision entry to a project's main.md",
        "args": [
            {"flags": ["target"], "help": "Session id, or project/repository name"},
            {"flags": ["text"], "nargs": "?", "default": None,
             "help": "Decision text"},
        ],
    },
    {"name": "main", "help": "Select the current session's main project record"},
    {
        "name": "sub", "help": "Select or create a subproject for the current session",
        "args": [
            {"flags": ["name"], "help": "Subproject ID"},
            {"flags": ["-f", "--force"], "action": "store_true",
             "help": "Create NAME even when it resembles an existing subproject"},
        ],
    },
    {"name": "subs", "help": "List subprojects for the current session's project"},
    {
        "name": "restart", "help": "Stop and restart an owrap session",
        "args": [
            {"flags": ["project_name"], "nargs": "?", "default": None,
             "help": "Project ID"},
            _SHELL_PID,
            _SESSION_FILE,
            {"flags": ["--force"], "action": "store_true", "default": False,
             "help": "Kill server and clear all sessions before starting fresh"},
            flag(_SESSION_ID, help="Session ID to restart"),
        ],
    },
    {
        "name": "setup", "help": "Configure owrap for a workspace",
        "args": [
            {"flags": ["path"], "nargs": "?", "default": None,
             "help": "Path to workspace directory (derives name from basename)"},
            {"flags": ["--name"], "type": str, "default": None,
             "help": "Workspace name (explicit override)"},
            {"flags": ["--workspace"], "type": str, "default": None,
             "help": "Path to workspace (used with --name for explicit override)"},
            {"flags": ["--docs-root", "--records-root", "--research-root"],
             "dest": "docs_root", "metavar": "PATH", "type": str, "default": None,
             "help": "Path to project and repository records"},
            {"flags": ["--allow-all"], "action": "store_true", "default": None,
             "help": "Allow all permissions"},
            {"flags": ["--oread"], "action": "store_true", "default": None,
             "help": "Use oread for all file reads"},
            {"flags": ["--no-oread"], "dest": "oread", "action": "store_false",
             "help": "Do not use oread for file reads"},
            {"flags": ["--planner"], "dest": "planners", "action": "append",
             "choices": ("claude", "codex", "opencode"), "metavar": "HARNESS",
             "help": "Install planner manual for HARNESS; repeat for multiple "
                     "harnesses"},
            {"flags": ["--executor"], "dest": "executors", "action": "append",
             "choices": ("claude", "codex", "opencode"), "metavar": "HARNESS",
             "help": "Install executor manual for HARNESS; repeat for multiple "
                     "harnesses"},
        ],
    },
    {"name": "sync", "help": "Re-apply staged templates to project files"},
    {
        "name": "read", "help": "Read a file via opencode",
        "args": [
            {"flags": ["-f", "--file"], "nargs": "+", "required": False,
             "default": None, "dest": "files",
             "help": "File or directory path (repeatable for -g grep)"},
            {"flags": ["-g", "--grep"], "type": str, "default": None,
             "help": "Grep pattern (fast, no opencode)"},
            {"flags": ["-s", "--summarise"], "action": "store_true",
             "help": "Summarise content"},
            {"flags": ["-d", "--details"], "type": str, "default": None,
             "help": "Focus details"},
            {"flags": ["--id", "-i"], "type": str, "default": None,
             "help": "Read ID for parallel tracking"},
            _DEBUG,
            flag(_TIMEOUT, help="Timeout in seconds (default: 55)"),
            _LOG_TIME,
            {"flags": ["-v", "--verbose"], "action": "store_true", "default": False,
             "help": "Full cat: bypass the 100-line limit"},
            {"flags": ["--list-styles"], "action": "store_true", "default": False,
             "help": "List all prompt styles and file-type extension defaults"},
            {"flags": ["-p", "--prompt-style"], "type": str, "default": None,
             "help": "Summary prompt style: default, terse, structured, code, "
                     "exec, bullets"},
        ],
    },
    {
        "name": "run", "help": "Run a task via opencode",
        "args": [
            {"flags": ["--msg"], "type": str, "default": None,
             "help": "Single-line message for task mode"},
            {"flags": ["--id", "-i"], "type": str, "default": None,
             "help": "Msg ID for parallel tracking"},
            {"flags": ["--input"], "type": str, "default": None,
             "help": "Input file path"},
            flag(_TIMEOUT, help="Timeout in seconds (default: 180 for --msg)"),
            _DEBUG,
            _LOG_TIME,
            {"flags": ["--add-context"], "action": "store_true",
             "help": "Tell the msg task to read context.md before responding"},
            _MODEL,
            _DISABLEWD,
        ],
    },
    {
        "name": "stat", "help": "Show all active owrap sessions and server status",
        "args": [
            {"flags": ["filter"], "nargs": "?", "default": None,
             "help": "Filter by session_id or research name"},
        ],
    },
    {
        "name": "cleanup",
        "help": "Remove stale session files and dead server state",
        "args": [
            {"flags": ["session_id"], "nargs": "?", "default": None,
             "help": "Partial session ID or filename prefix to target; pass "
                     "'trash' to sweep .trash of entries past retention"},
        ],
    },
    {
        "name": "restore",
        "help": "Restore a session moved to .trash by owrap end/stop",
        "args": [
            {"flags": ["what"], "choices": ["trash"],
             "help": "Currently only 'trash' is supported"},
            {"flags": ["session_id"], "help": "Session ID to restore"},
        ],
    },
    {
        "name": "agent",
        "help": "Dispatch a self-contained agent dive (like --msg, but with "
                "its own timeout/log conventions)",
        "args": [
            {"flags": ["data"], "nargs": "?", "default": None,
             "help": "Self-contained agent instruction — your task and "
                     "context. Omit (or pass \"-\") to read the payload from "
                     "stdin instead (e.g. via a quoted heredoc), which avoids "
                     "shell-quoting issues for payloads containing code, "
                     "quotes, or shell metacharacters."},
            {"flags": ["--id", "-i"], "type": str, "default": None,
             "help": "Agent ID for parallel tracking"},
            flag(_TIMEOUT, help="Hard wall-clock timeout in seconds (default: 120)"),
            _MODEL,
            _DEBUG,
            _LOG_TIME,
            {"flags": ["--clear"], "action": "store_true",
             "help": "Clear agent output log before dispatching"},
            _DISABLEWD,
        ],
    },
    {
        "name": "exec", "aliases": ["work"],
        "help": "Execute the active plan via opencode",
        "args": [
            _DEBUG,
            _LOG_TIME,
            _MODEL,
            flag(_TIMEOUT, help="Hard wall-clock timeout in seconds (default: 600)"),
            _DISABLEWD,
        ],
    },
    {
        "name": "abort",
        "help": "Abort (SIGTERM) a running orun/oexec job by target (exec, "
                "task1, task2, ..., agent1, agent2, ...)",
        "args": [
            {"flags": ["target"],
             "help": "Job to abort: 'exec', 'task', 'task1', 'task2', "
                     "'msg1', ..., 'agent1', ..."},
            flag(_SESSION, help="Session ID override"),
        ],
    },
    {
        "name": "agents",
        "help": "Manage subagent dive output (use `oagent clear` instead of "
                "this directly)",
        "args": [
            {"flags": ["action"], "choices": ["clear"],
             "help": "clear: wipe agents/output.log and agents/output/ for "
                     "the current session"},
        ],
    },
    {
        "name": "killservers",
        "help": "Kill all servers and running tasks without clearing "
                "session/context state",
        "args": [
            flag(_SESSION, help="Limit to a specific session ID"),
        ],
    },
    {
        "name": "f",
        "help": "Run a fallback --execf/--taskf invocation directly (no "
                "server); mode inferred from filename",
        "args": [
            {"flags": ["path"],
             "help": "Path to a plan or task .md file, or 'tstop'/'estop' "
                     "to stop a running task/exec fallback"},
        ],
    },
    {
        "name": "spawn", "help": "Start a child session inheriting the current target",
        "args": [
            {"flags": ["child"], "nargs": "?", "default": None,
             "help": "Optional child session name"},
        ],
    },
    {
        "name": "temp", "help": "Start an independent temporary session",
        "args": [{"flags": ["name"], "nargs": "?", "default": None}],
    },
    {
        "name": "collapse", "help": "Preview or apply a child session context collapse",
        "args": [
            _SESSION,
            _APPLY,
        ],
    },
    {
        "name": "update-home",
        "help": "Point OWRAP_HOME at a new path (default: lightweight "
                "repoint; --migrate: backs up, stops live processes, "
                "moves, re-syncs)",
        "args": [
            {"flags": ["path"], "help": "New absolute path for OWRAP_HOME"},
            {"flags": ["--dry-run"], "action": "store_true", "default": False,
             "help": "Show what would happen without making any changes"},
            {"flags": ["--migrate"], "action": "store_true", "default": False,
             "help": "Relocate existing content: backup, stop server pool + "
                     "daemon, atomically move, re-sync current workspace"},
        ],
    },
    {"name": "ctx-hook", "help": "PreCompact hook handler"},
    {
        "name": "ctx-worker", "help": "Context-manager background worker",
        "args": [
            {"flags": ["--input"], "type": str, "required": True,
             "help": "Input JSON path"},
        ],
    },
    {"name": "ctx", "help": "Dispatch an Update Context task for this window now"},
    {
        "name": "updr",
        "help": "Dispatch an Update Protocol task for this window now",
        "args": [
            {"flags": ["subproject"], "nargs": "?", "default": None,
             "help": "Subproject to update (default: this session's target)"},
            {"flags": ["--ctx"], "action": "store_true",
             "help": "Also run Update Context, in the same single "
                     "background dispatch"},
        ],
    },
    {
        "name": "touched",
        "help": "Report touched file paths for the next context-manager dispatch",
        "args": [
            {"flags": ["paths"], "nargs": "+", "help": "One or more file paths"},
            {"flags": ["--note"], "default": None,
             "help": "One-line note applied to every path given"},
        ],
    },
    {
        "name": "backup",
        "help": "Snapshot a project/subproject/repository's record files",
        "args": [
            {"flags": ["target"],
             "help": "Session id, or project/subproject/repository name"},
        ],
    },
    {
        "name": "retrieve",
        "help": "Restore record files from an `owrap backup` snapshot",
        "args": [
            {"flags": ["target"],
             "help": "Session id, or project/subproject/repository name"},
            {"flags": ["timestamp"], "nargs": "?", "default": None,
             "help": "Backup timestamp (or an unambiguous prefix), or "
                     "'latest' — omit to list available backups"},
        ],
    },
    {
        "name": "delete", "help": "Delete something (backup only, for now)",
        "args": [
            {"flags": ["what"], "choices": ["backup"]},
            {"flags": ["target"],
             "help": "Session id, or project/subproject/repository name"},
            {"flags": ["which"], "nargs": "?", "default": "latest",
             "help": "'latest' (default), 'all', or a timestamp prefix"},
        ],
    },
    {
        "name": "get", "help": "Inspect session files",
        "args": [
            {"flags": ["what"], "choices": [
                "plan", "input", "context", "session", "memory",
                "project", "proj", "todo", "area", "research", "project-id",
                "subproject", "sub", "subs", "repository", "repo", "repos",
                "self",
                "config", "home", "agents",
                "output", "runtime", "transcript",
            ]},
            {"flags": ["kind"], "nargs": "?", "default": None,
             "choices": ["msg", "task", "agent", "exec"]},
            _SESSION,
            {"flags": ["--id"], "default": None},
            {"flags": ["--head"], "type": int, "default": 5},
            {"flags": ["--tail"], "type": int, "default": 5},
            {"flags": ["--ev"], "default": None, "help": "Filter events by prefix"},
            {"flags": ["--sid"], "default": None, "help": "Filter by session ID"},
            {"flags": ["--ccsid"], "default": None,
             "help": "Attached window id (default: current CLAUDE_CODE_SESSION_ID)"},
        ],
    },
    {"name": "daemon", "help": "Run the owrap daemon"},
    {
        "name": "p", "help": "Hook permission check (reads staged permit.json)",
        "args": [{"flags": ["--workspace"], "default": None}],
    },
    {
        "name": "permit",
        "help": "Inspect or toggle the permit auto-approve-all bypass",
        "args": [
            {"flags": ["action"], "choices": ["status", "bypass-all"]},
            {"flags": ["state"], "nargs": "?", "choices": ["on", "off"],
             "default": None},
        ],
    },
    {
        "name": "set", "help": "Set a workspace config value",
        "subparsers": {
            "dest": "set_target",
            "commands": [
                {
                    "name": "model",
                    "help": "Search live opencode models and set one on a "
                            "model slot",
                    "args": [
                        {"flags": ["slot"], "choices": [
                            "runner", "context_manager", "context_fallback",
                            "daemon_default",
                        ]},
                        {"flags": ["query"],
                         "help": "Substring to search for in available model names"},
                        {"flags": ["--workspace"], "default": None,
                         "help": "Workspace name (default: default_workspace)"},
                    ],
                },
            ],
        },
    },
    {
        "name": "wait", "help": "Wait for task/read/msg completion",
        "args": [
            {"flags": ["type"], "choices": ["run", "exec", "read", "msg", "input"]},
            {"flags": ["id"], "nargs": "?", "default": None,
             "help": "ID to wait for (required for read/msg)"},
            flag(_SESSION, help="Session ID override"),
            {"flags": ["--timeout"], "type": int, "default": None,
             "help": "Timeout in seconds"},
        ],
    },
]


def add_arguments(target, arg_specs):
    """
    Apply a list of argparse.add_argument() specs to `target`, routing any
    spec with a `group` key through a mutually-exclusive group scoped to
    that name (created on first use).
    """
    groups = {}
    for spec in arg_specs:
        spec = dict(spec)
        group_name = spec.pop("group", None)
        flags = spec.pop("flags")
        destination = target
        if group_name is not None:
            if group_name not in groups:
                groups[group_name] = target.add_mutually_exclusive_group()
            destination = groups[group_name]
        destination.add_argument(*flags, **spec)


def build_subcommand(subparsers, spec):
    """
    Add one subcommand (and, if given, its own nested subcommands) to
    `subparsers` from a schema entry.
    """
    kwargs = {}
    if spec.get("help") is not None:
        kwargs["help"] = spec["help"]
    if spec.get("aliases"):
        kwargs["aliases"] = spec["aliases"]
    sub = subparsers.add_parser(spec["name"], **kwargs)
    add_arguments(sub, spec.get("args", []))
    nested = spec.get("subparsers")
    if nested:
        nested_subparsers = sub.add_subparsers(dest=nested["dest"])
        for nested_spec in nested["commands"]:
            build_subcommand(nested_subparsers, nested_spec)
    return sub
