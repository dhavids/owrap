import argparse
import shutil
import sys
import time
from pathlib import Path

from .session import (
    StartRunner, StopRunner, RefreshRunner, RestartRunner,
    CleanupRunner, EndRunner, AttachRunner, DetachRunner,
    UpdateAreaRunner, RestoreRunner,
)
from .commands import (
    AbortRunner, ExecRunner, ReadRunner, RunRunner,
    SetupRunner, WaitRunner,
)
from .commands.sync_cmd import SyncRunner
from .commands.daemon import DaemonRunner
from .manager import Manager
from .utils.paths import _read_config, get_workspace_config
from .utils.arg_parser import OwrapArgumentParser
from .utils.log import rtlog

_UNLOGGED_CMDS = {"stat", "get", "permit", "wait", "set"}


# Command Handlers

def _cmd_start(args, manager, logger, allow_all):
    StartRunner(manager, logger, allow_all=allow_all).run(
        shell_pid=args.shell_pid,
        session_file=args.session_file,
        research=args.research,
        session_id=getattr(args, 'session_id', None),
        area=getattr(args, 'area', None),
        child=getattr(args, 'child', None),
    )


def _cmd_stop(args, manager, logger, allow_all):
    target = (
        getattr(args, 'session_id', None)
        or getattr(args, 'target', None)
    )
    StopRunner(manager, logger, allow_all=allow_all).run(
        session_file=args.session_file,
        force=args.force,
        target=target,
    )


def _cmd_end(args, manager, logger, allow_all):
    target = (
        getattr(args, 'session_id', None)
        or getattr(args, 'target', None)
    )
    EndRunner(manager, logger, allow_all=allow_all).run(
        session_file=args.session_file,
        target=target,
    )


def _cmd_refresh(args, manager, logger, allow_all):
    RefreshRunner(manager, logger, allow_all=allow_all).run(
        shell_pid=args.shell_pid,
        session_file=args.session_file,
        research=args.research,
        session_id=getattr(args, 'session_id', None),
        area=getattr(args, 'area', None),
    )


def _cmd_attach(args, manager, logger, allow_all):
    AttachRunner(manager, logger, allow_all=allow_all).run(
        target_session_id=args.target_session_id,
    )


def _cmd_detach(args, manager, logger, allow_all):
    DetachRunner(manager, logger, allow_all=allow_all).run()


def _cmd_todo(args, manager, logger, allow_all):
    from .commands.todo_cmd import TodoRunner
    if args.target == "clear":
        TodoRunner().run_clear(args.arg2)
    elif args.target == "done":
        TodoRunner().run_done(args.arg2, args.arg3)
    else:
        TodoRunner().run(args.target, args.arg2, args.arg3)


def _cmd_restart(args, manager, logger, allow_all):
    RestartRunner(manager, logger, allow_all=allow_all).run(
        shell_pid=args.shell_pid,
        session_file=args.session_file,
        research=args.research,
        force=args.force,
        session_id=getattr(args, 'session_id', None),
    )


def _cmd_setup(args, manager, logger, allow_all):
    SetupRunner().run(
        path=args.path,
        project_name=args.name,
        workspace=args.workspace,
        research_root=args.research_root,
        allow_all=args.allow_all,
        oread=args.oread,
    )


def _cmd_sync(args, manager, logger, allow_all):
    SyncRunner().run()


def _cmd_read(args, manager, logger, allow_all):
    if getattr(args, 'list_styles', False):
        ReadRunner(manager, logger, allow_all=allow_all).list_styles()
        sys.exit(0)
    if args.files is None and args.grep is None:
        import sys as _sys
        print(
            "error: -f/--file required unless using -g/--grep",
            file=_sys.stderr,
        )
        _sys.exit(1)
    ReadRunner(manager, logger, allow_all=allow_all).run(
        (
            args.files[0]
            if args.files and len(args.files) == 1
            else args.files
        ),
        summarise=args.summarise,
        details=args.details,
        log_time=args.log_time,
        grep=args.grep,
        read_id=getattr(args, 'id', None),
        timeout=getattr(args, 'timeout', None),
        verbose=args.verbose,
        prompt_style=getattr(args, 'prompt_style', None),
    )


def _cmd_run(args, manager, logger, allow_all):
    RunRunner(
        manager, logger, allow_all=allow_all,
        add_context=args.add_context,
        model=args.model,
        disablewd=args.disablewd,
    ).run(
        msg=args.msg,
        msg_id=getattr(args, 'id', None),
        input_path=Path(args.input) if args.input else None,
        log_time=args.log_time,
        timeout=getattr(args, 'timeout', None),
    )


def _cmd_agent(args, manager, logger, allow_all):
    from .commands.agents import AgentsRunner
    agent_data = args.data
    if agent_data is None or agent_data == "-":
        import sys as _sys
        agent_data = _sys.stdin.read()
    AgentsRunner(
        manager, logger, allow_all=allow_all,
        model=args.model,
        disablewd=args.disablewd,
    ).run_agent(
        data=agent_data,
        agent_id=getattr(args, 'id', None),
        log_time=args.log_time,
        timeout=getattr(args, 'timeout', None),
        clear=args.clear,
    )


def _cmd_exec(args, manager, logger, allow_all):
    ExecRunner(
        manager, logger, allow_all=allow_all,
        model=args.model,
        disablewd=args.disablewd,
    ).run(
        log_time=args.log_time,
        timeout=getattr(args, 'timeout', None),
    )


def _cmd_abort(args, manager, logger, allow_all):
    AbortRunner(manager, logger, allow_all=allow_all).run(
        target=args.target,
        session_id=getattr(args, "session", None),
    )


def _cmd_agents(args, manager, logger, allow_all):
    from .commands.agents import AgentsRunner
    AgentsRunner(manager, logger, allow_all=allow_all).run(action=args.action)


def _cmd_killservers(args, manager, logger, allow_all):
    from .session.stop import KillServersRunner
    KillServersRunner().run(session_id=getattr(args, "session", None))


def _cmd_daemon(args, manager, logger, allow_all):
    DaemonRunner(manager, logger, allow_all=allow_all).run()


def _cmd_update_area(args, manager, logger, allow_all):
    UpdateAreaRunner(
        manager, logger, allow_all=allow_all,
    ).run(
        research=args.research,
        area=args.area,
        child=args.child,
    )


def _cmd_spawn(args, manager, logger, allow_all):
    from .session.start import SpawnRunner
    SpawnRunner(manager, logger, allow_all=allow_all).run(child=args.child)


def _cmd_update_home(args, manager, logger, allow_all):
    from .commands.update_home import UpdateHomeRunner
    UpdateHomeRunner(
        manager, logger, allow_all=allow_all,
    ).run(
        new_path=args.path,
        dry_run=args.dry_run,
        migrate=args.migrate,
    )


def _cmd_wait(args, manager, logger, allow_all):
    WaitRunner(manager, logger, allow_all=allow_all).run(
        wait_type=args.type,
        wait_id=args.id,
        session_id=args.session,
        timeout=args.timeout,
    )


def _cmd_stat(args, manager, logger, allow_all):
    from .session.stat import StatRunner
    sys.exit(StatRunner(manager, logger, allow_all).run(args))


def _cmd_cleanup(args, manager, logger, allow_all):
    if getattr(args, "session_id", None) == "trash":
        from .utils.session.trash import sweep_trash
        removed = sweep_trash()
        if removed:
            print(
                f"Trash sweep: {removed} session(s) permanently removed "
                f"(past retention)."
            )
        else:
            print("Trash sweep: nothing past retention.")
        sys.exit(0)
    sys.exit(CleanupRunner(manager, logger, allow_all).run(args))


def _cmd_restore(args, manager, logger, allow_all):
    sys.exit(RestoreRunner(manager, logger, allow_all).run(args))


def _cmd_f(args, manager, logger, allow_all):
    from .commands.fallback import FallbackRunner
    FallbackRunner().run(args.path)


def _cmd_ctx_hook(args, manager, logger, allow_all):
    from .commands.context_manager import CtxHookRunner
    CtxHookRunner().run()


def _cmd_ctx_worker(args, manager, logger, allow_all):
    from .commands.context_manager import CtxWorkerRunner
    CtxWorkerRunner().run(input_path=Path(args.input))


def _cmd_ctx(args, manager, logger, allow_all):
    from .commands.context_manager import CtxWorkerRunner
    CtxWorkerRunner().run_manual(mode="ctx")


def _cmd_updr(args, manager, logger, allow_all):
    from .commands.context_manager import CtxWorkerRunner
    mode = None if args.ctx else "updr"
    CtxWorkerRunner().run_manual(mode=mode, area=args.area)


def _cmd_touched(args, manager, logger, allow_all):
    from .commands.touched_cmd import TouchedRunner
    TouchedRunner().run(args.paths, note=args.note)


def _cmd_backup(args, manager, logger, allow_all):
    from .commands.backup_cmd import BackupRunner
    BackupRunner().run(args.research)


def _cmd_retrieve(args, manager, logger, allow_all):
    from .commands.backup_cmd import RetrieveRunner
    RetrieveRunner().run(args.research, timestamp=args.timestamp)


def _cmd_delete(args, manager, logger, allow_all):
    if args.what == "backup":
        from .commands.backup_cmd import DeleteBackupRunner
        DeleteBackupRunner().run(args.research, which=args.which)


def _cmd_get(args, manager, logger, allow_all):
    from .commands.get_cmd import GetRunner
    runner = GetRunner()
    if args.what == "output":
        sys.exit(
            runner.run_output(
                kind=args.kind,
                dispatch_id=args.id,
                head=args.head,
                tail=args.tail,
                session_id=args.session,
            )
            or 0
        )
    if args.what == "runtime":
        sys.exit(runner.run_runtime(
            tail=args.tail, ev_prefix=args.ev, sid=args.sid,
        ) or 0)
    if args.what == "transcript":
        sys.exit(runner.run_transcript(
            session_id=args.session, ccsid=args.ccsid,
        ) or 0)
    sys.exit(runner.run(args.what, session_id=args.session,
                        dispatch_id=args.id) or 0)


_COMMAND_HANDLERS = {
    "start": _cmd_start,
    "stop": _cmd_stop,
    "end": _cmd_end,
    "refresh": _cmd_refresh,
    "attach": _cmd_attach,
    "detach": _cmd_detach,
    "todo": _cmd_todo,
    "restart": _cmd_restart,
    "setup": _cmd_setup,
    "sync": _cmd_sync,
    "read": _cmd_read,
    "run": _cmd_run,
    "agent": _cmd_agent,
    "exec": _cmd_exec,
    "work": _cmd_exec,
    "abort": _cmd_abort,
    "agents": _cmd_agents,
    "killservers": _cmd_killservers,
    "daemon": _cmd_daemon,
    "update-area": _cmd_update_area,
    "spawn": _cmd_spawn,
    "update-home": _cmd_update_home,
    "wait": _cmd_wait,
    "stat": _cmd_stat,
    "cleanup": _cmd_cleanup,
    "restore": _cmd_restore,
    "f": _cmd_f,
    "ctx-hook": _cmd_ctx_hook,
    "ctx-worker": _cmd_ctx_worker,
    "ctx": _cmd_ctx,
    "updr": _cmd_updr,
    "touched": _cmd_touched,
    "backup": _cmd_backup,
    "retrieve": _cmd_retrieve,
    "delete": _cmd_delete,
    "get": _cmd_get,
}


def main():
    parser = OwrapArgumentParser(
        description="OWrap Runner Utility", prog="owrap",
    )

    parser.add_argument(
        "-a", "--allow-all", action="store_true",
        help="Pass --dangerously-skip-permissions to opencode",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    start_parser = subparsers.add_parser("start", help="Start an owrap session")
    start_parser.add_argument(
        "research", nargs="?", default=None,
        help="Research project name",
    )
    start_parser.add_argument("--shell-pid", type=int, default=None, help="Shell PID")
    start_parser.add_argument(
        "--session-file", type=str, default=None,
        help="Session file path",
    )
    start_parser.add_argument(
        "-i", "--session-id", type=str, default=None,
        help="Session ID: attach if exists, create with this ID if not",
    )
    start_parser.add_argument(
        "area", nargs="?", default=None,
        help="Area within research (e.g. self-translator)",
    )
    start_parser.add_argument(
        "child", nargs="?", default=None,
        help="Child suffix — session's area becomes '<area>-<child>'",
    )

    stop_parser = subparsers.add_parser("stop", help="Stop an owrap session")
    stop_parser.add_argument(
        "target", nargs="?", default=None,
        help="Session ID prefix or research name to stop (alias for -i/--session-id)",
    )
    stop_parser.add_argument(
        "-i", "--session-id", type=str, default=None,
        help="Session ID or research name to stop (alias for positional target)",
    )
    stop_parser.add_argument(
        "--session-file", type=str, default=None,
        help="Session file path",
    )
    stop_parser.add_argument(
        "--force", action="store_true", default=False,
        help="Kill server and clear all sessions even if others are active",
    )

    end_parser = subparsers.add_parser(
        "end", help="End this session only (server keeps running)",
    )
    end_parser.add_argument(
        "target", nargs="?", default=None,
        help="Session ID prefix or research name to end (alias for -i/--session-id)",
    )
    end_parser.add_argument(
        "-i", "--session-id", type=str, default=None,
        help="Session ID or research name to end (alias for positional target)",
    )
    end_parser.add_argument("--session-file", type=str, default=None)

    refresh_parser = subparsers.add_parser("refresh", help="Refresh an owrap session")
    refresh_parser.add_argument(
        "research", nargs="?", default=None,
        help="Research project name",
    )
    refresh_parser.add_argument("--shell-pid", type=int, default=None, help="Shell PID")
    refresh_parser.add_argument(
        "--session-file", type=str, default=None,
        help="Session file path",
    )
    refresh_parser.add_argument(
        "-i", "--session-id", type=str, default=None,
        help="Session ID to refresh (skips env resolution)",
    )
    refresh_parser.add_argument(
        "area", nargs="?", default=None,
        help="Update area for this session",
    )

    attach_parser = subparsers.add_parser(
        "attach", help="Bind an existing session to this Claude window",
    )
    attach_parser.add_argument("target_session_id", help="Session ID to attach to")
    attach_parser.add_argument(
        "--shell-pid", type=int, default=None, help="Shell PID (ignored)",
    )

    subparsers.add_parser(
        "detach", help="Release this window's attachment to its session",
    )

    todo_parser = subparsers.add_parser(
        "todo",
        help="Add, insert, mark done, or clear todo entries for a research/area",
    )
    todo_parser.add_argument(
        "target",
        help=(
            "Session id, research/area name, 'clear' to clear done items, "
            "or 'done' to mark one item done"
        ),
    )
    todo_parser.add_argument(
        "arg2", nargs="?", default=None,
        help="Todo text, position, or (after 'clear'/'done') the target",
    )
    todo_parser.add_argument(
        "arg3", nargs="?", default=None,
        help="Todo text when arg2 is a position, or (after 'done') the selector",
    )

    restart_parser = subparsers.add_parser(
        "restart", help="Stop and restart an owrap session",
    )
    restart_parser.add_argument(
        "research", nargs="?", default=None,
        help="Research project name",
    )
    restart_parser.add_argument("--shell-pid", type=int, default=None, help="Shell PID")
    restart_parser.add_argument(
        "--session-file", type=str, default=None,
        help="Session file path",
    )
    restart_parser.add_argument(
        "--force", action="store_true", default=False,
        help="Kill server and clear all sessions before starting fresh",
    )
    restart_parser.add_argument(
        "-i", "--session-id", type=str, default=None,
        help="Session ID to restart",
    )

    setup_parser = subparsers.add_parser("setup", help="Configure owrap for a workspace")
    setup_parser.add_argument(
        "path", nargs="?", default=None,
        help="Path to workspace directory (derives name from basename)",
    )
    setup_parser.add_argument(
        "--name", type=str, default=None,
        help="Workspace name (explicit override)",
    )
    setup_parser.add_argument(
        "--workspace", type=str, default=None,
        help="Path to workspace (used with --name for explicit override)",
    )
    setup_parser.add_argument(
        "--research-root", type=str, default=None,
        help="Path to research root",
    )
    setup_parser.add_argument(
        "--allow-all", action="store_true", default=None,
        help="Allow all permissions",
    )
    setup_parser.add_argument(
        "--oread", action="store_true", default=None,
        help="Use oread for all file reads",
    )
    setup_parser.add_argument(
        "--no-oread", dest="oread", action="store_false",
        help="Do not use oread for file reads",
    )

    sync_parser = subparsers.add_parser(
        "sync", help="Re-apply staged templates to project files",
    )

    read_parser = subparsers.add_parser("read", help="Read a file via opencode")
    run_parser = subparsers.add_parser("run", help="Run a task via opencode")
    exec_parser = subparsers.add_parser(
        "exec", aliases=["work"],
        help="Execute the active plan via opencode",
    )

    stat_parser = subparsers.add_parser(
        "stat", help="Show all active owrap sessions and server status",
    )
    stat_parser.add_argument(
        "filter", nargs="?", default=None,
        help="Filter by session_id or research name",
    )

    cleanup_parser = subparsers.add_parser(
        "cleanup", help="Remove stale session files and dead server state",
    )
    cleanup_parser.add_argument(
        "session_id", nargs="?", default=None,
        help=(
            "Partial session ID or filename prefix to target; pass 'trash' "
            "to sweep .trash of entries past retention"
        ),
    )

    restore_parser = subparsers.add_parser(
        "restore", help="Restore a session moved to .trash by owrap end/stop",
    )
    restore_parser.add_argument(
        "what", choices=["trash"],
        help="Currently only 'trash' is supported",
    )
    restore_parser.add_argument("session_id", help="Session ID to restore")

    read_parser.add_argument(
        "-f", "--file", nargs="+", required=False, default=None,
        dest="files", help="File or directory path (repeatable for -g grep)",
    )
    read_parser.add_argument(
        "-g", "--grep", type=str, default=None,
        help="Grep pattern (fast, no opencode)",
    )
    read_parser.add_argument(
        "-s", "--summarise", action="store_true",
        help="Summarise content",
    )
    read_parser.add_argument(
        "-d", "--details", type=str, default=None,
        help="Focus details",
    )
    read_parser.add_argument(
        "--id", "-i", type=str, default=None,
        help="Read ID for parallel tracking",
    )
    read_parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    read_parser.add_argument(
        "-t", "--timeout", type=int, default=None,
        help="Timeout in seconds (default: 55)",
    )
    read_parser.add_argument(
        "--log-time", action="store_true",
        help="Show the [timing] block (debugging/tests only)",
    )
    read_parser.add_argument(
        "-v", "--verbose", action="store_true", default=False,
        help="Full cat: bypass the 100-line limit",
    )
    read_parser.add_argument(
        "--list-styles", action="store_true", default=False,
        help="List all prompt styles and file-type extension defaults",
    )
    read_parser.add_argument(
        "-p", "--prompt-style", type=str, default=None,
        help="Summary prompt style: default, terse, structured, code, exec, bullets",
    )

    run_parser.add_argument(
        "--msg", type=str, default=None,
        help="Single-line message for task mode",
    )
    run_parser.add_argument(
        "--id", "-i", type=str, default=None,
        help="Msg ID for parallel tracking",
    )
    run_parser.add_argument(
        "--input", type=str, default=None,
        help="Input file path",
    )
    run_parser.add_argument(
        "-t", "--timeout", type=int, default=None,
        help="Timeout in seconds (default: 180 for --msg)",
    )
    run_parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    run_parser.add_argument(
        "--log-time", action="store_true",
        help="Show the [timing] block (debugging/tests only)",
    )
    run_parser.add_argument(
        "--add-context", action="store_true",
        help="Tell the msg task to read context.md before responding",
    )
    run_parser.add_argument(
        "--model", "-m", type=str, default=None,
        help="Model override",
    )
    run_parser.add_argument(
        "--disablewd", action="store_true", default=False,
        help="Disable stall/no-output watchdog; hard timeout still applies",
    )

    agent_parser = subparsers.add_parser(
        "agent",
        help=(
            "Dispatch a self-contained agent dive (like --msg, but with its "
            "own timeout/log conventions)"
        ),
    )
    agent_parser.add_argument(
        "data", nargs="?", default=None,
        help=(
            "Self-contained agent instruction — your task and context. Omit "
            "(or pass \"-\") to read the payload from stdin instead (e.g. "
            "via a quoted heredoc), which avoids shell-quoting issues for "
            "payloads containing code, quotes, or shell metacharacters."
        ),
    )
    agent_parser.add_argument(
        "--id", "-i", type=str, default=None,
        help="Agent ID for parallel tracking",
    )
    agent_parser.add_argument(
        "-t", "--timeout", type=int, default=None,
        help="Hard wall-clock timeout in seconds (default: 120)",
    )
    agent_parser.add_argument(
        "--model", "-m", type=str, default=None,
        help="Model override",
    )
    agent_parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    agent_parser.add_argument(
        "--log-time", action="store_true",
        help="Show the [timing] block (debugging/tests only)",
    )
    agent_parser.add_argument(
        "--clear", action="store_true",
        help="Clear agent output log before dispatching",
    )
    agent_parser.add_argument(
        "--disablewd", action="store_true", default=False,
        help="Disable stall/no-output watchdog; hard timeout still applies",
    )

    exec_parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    exec_parser.add_argument(
        "--log-time", action="store_true",
        help="Show the [timing] block (debugging/tests only)",
    )
    exec_parser.add_argument(
        "--model", "-m", type=str, default=None,
        help="Model override",
    )
    exec_parser.add_argument(
        "-t", "--timeout", type=int, default=None,
        help="Hard wall-clock timeout in seconds (default: 600)",
    )
    exec_parser.add_argument(
        "--disablewd", action="store_true", default=False,
        help="Disable stall/no-output watchdog; hard timeout still applies",
    )

    abort_parser = subparsers.add_parser(
        "abort",
        help=(
            "Abort (SIGTERM) a running orun/oexec job by target (exec, task1, task2, "
            "..., agent1, agent2, ...)"
        ),
    )
    abort_parser.add_argument(
        "target",
        help="Job to abort: 'exec', 'task', 'task1', 'task2', 'msg1', ..., 'agent1', ...",
    )
    abort_parser.add_argument(
        "--session", type=str, default=None,
        help="Session ID override",
    )

    agents_parser = subparsers.add_parser(
        "agents",
        help="Manage subagent dive output (use `oagent clear` instead of this directly)",
    )
    agents_parser.add_argument(
        "action", choices=["clear"],
        help="clear: wipe agents/output.log and agents/output/ for the current session",
    )

    killservers_parser = subparsers.add_parser(
        "killservers",
        help="Kill all servers and running tasks without clearing session/context state",
    )
    killservers_parser.add_argument(
        "--session", type=str, default=None,
        help="Limit to a specific session ID",
    )

    fallback_parser = subparsers.add_parser(
        "f",
        help=(
            "Run a fallback --execf/--taskf invocation directly (no server); "
            "mode inferred from filename"
        ),
    )
    fallback_parser.add_argument(
        "path",
        help=(
            "Path to a plan or task .md file, or 'tstop'/'estop' to stop a "
            "running task/exec fallback"
        ),
    )

    update_area_parser = subparsers.add_parser(
        "update-area", help="Set research and area for the current session",
    )
    update_area_parser.add_argument("research", help="Research name")
    update_area_parser.add_argument(
        "area", help="Area within research (e.g. self-translator)",
    )
    update_area_parser.add_argument(
        "child", nargs="?", default=None,
        help="Child suffix if this area is a child area (omit to clear/not set)",
    )

    spawn_parser = subparsers.add_parser(
        "spawn",
        help="Spawn a child area under the current session's area and rebind to it",
    )
    spawn_parser.add_argument(
        "child",
        help="Child suffix — current session's area becomes '<area>-<child>'",
    )

    update_home_parser = subparsers.add_parser(
        "update-home",
        help=(
            "Point OWRAP_HOME at a new path (default: lightweight repoint; "
            "--migrate: backs up, stops live processes, moves, re-syncs)"
        ),
    )
    update_home_parser.add_argument(
        "path", help="New absolute path for OWRAP_HOME",
    )
    update_home_parser.add_argument(
        "--dry-run", action="store_true", default=False,
        help="Show what would happen without making any changes",
    )
    update_home_parser.add_argument(
        "--migrate", action="store_true", default=False,
        help=(
            "Relocate existing content: backup, stop server pool + daemon, "
            "atomically move, re-sync current workspace"
        ),
    )

    ctx_hook_parser = subparsers.add_parser(
        "ctx-hook", help="PreCompact hook handler",
    )

    ctx_worker_parser = subparsers.add_parser(
        "ctx-worker", help="Context-manager background worker",
    )
    ctx_worker_parser.add_argument(
        "--input", type=str, required=True,
        help="Input JSON path",
    )

    ctx_parser = subparsers.add_parser(
        "ctx", help="Dispatch an Update Context task for this window now",
    )

    updr_parser = subparsers.add_parser(
        "updr", help="Dispatch an Update Protocol task for this window now",
    )
    updr_parser.add_argument(
        "area", nargs="?", default=None,
        help="Area to update (default: this session's configured area)",
    )
    updr_parser.add_argument(
        "--ctx", action="store_true",
        help="Also run Update Context, in the same single background dispatch",
    )

    touched_parser = subparsers.add_parser(
        "touched",
        help="Report touched file paths for the next context-manager dispatch",
    )
    touched_parser.add_argument("paths", nargs="+", help="One or more file paths")
    touched_parser.add_argument(
        "--note", default=None, help="One-line note applied to every path given",
    )

    backup_parser = subparsers.add_parser(
        "backup", help="Snapshot a research's memory/projects/todo files",
    )
    backup_parser.add_argument("research", help="Research name")

    retrieve_parser = subparsers.add_parser(
        "retrieve",
        help="Restore memory/projects/todo files from an `owrap backup` snapshot",
    )
    retrieve_parser.add_argument("research", help="Research name")
    retrieve_parser.add_argument(
        "timestamp", nargs="?", default=None,
        help="Backup timestamp (or an unambiguous prefix), or 'latest' — "
             "omit to list available backups",
    )

    delete_parser = subparsers.add_parser(
        "delete", help="Delete something (backup only, for now)",
    )
    delete_parser.add_argument("what", choices=["backup"])
    delete_parser.add_argument("research", help="Research name")
    delete_parser.add_argument(
        "which", nargs="?", default="latest",
        help="'latest' (default), 'all', or a timestamp prefix",
    )

    get_parser = subparsers.add_parser("get", help="Inspect session files")
    get_parser.add_argument(
        "what",
        choices=[
            "plan", "input", "context", "session", "memory",
            "project", "todo", "area", "research", "config", "home", "agents",
            "output", "runtime", "transcript",
        ],
    )
    get_parser.add_argument(
        "kind", nargs="?", default=None,
        choices=["msg", "task", "agent", "exec"],
    )
    get_parser.add_argument("--session", default=None)
    get_parser.add_argument("--id", default=None)
    get_parser.add_argument("--head", type=int, default=5)
    get_parser.add_argument("--tail", type=int, default=5)
    get_parser.add_argument("--ev", default=None, help="Filter events by prefix")
    get_parser.add_argument("--sid", default=None, help="Filter by session ID")
    get_parser.add_argument(
        "--ccsid", default=None,
        help="Attached window id (default: current CLAUDE_CODE_SESSION_ID)",
    )

    daemon_parser = subparsers.add_parser("daemon", help="Run the owrap daemon")

    p_parser = subparsers.add_parser(
        "p", help="PreToolUse permission check (reads staged permit.json)",
    )

    permit_cmd_parser = subparsers.add_parser(
        "permit", help="Inspect or toggle the permit auto-approve-all bypass",
    )
    permit_cmd_parser.add_argument("action", choices=["status", "bypass-all"])
    permit_cmd_parser.add_argument(
        "state", nargs="?", choices=["on", "off"], default=None,
    )

    set_parser = subparsers.add_parser("set", help="Set a workspace config value")
    set_subparsers = set_parser.add_subparsers(dest="set_target")
    set_model_parser = set_subparsers.add_parser(
        "model", help="Search live opencode models and set one on a model slot",
    )
    set_model_parser.add_argument(
        "slot",
        choices=["runner", "context_manager", "context_fallback", "daemon_default"],
    )
    set_model_parser.add_argument(
        "query", help="Substring to search for in available model names",
    )
    set_model_parser.add_argument(
        "--workspace", default=None, help="Workspace name (default: default_workspace)",
    )

    wait_parser = subparsers.add_parser("wait", help="Wait for task/read/msg completion")
    wait_parser.add_argument("type", choices=["run", "exec", "read", "msg", "input"])
    wait_parser.add_argument(
        "id", nargs="?", default=None,
        help="ID to wait for (required for read/msg)",
    )
    wait_parser.add_argument(
        "--session", type=str, default=None,
        help="Session ID override",
    )
    wait_parser.add_argument(
        "--timeout", type=int, default=None,
        help="Timeout in seconds",
    )

    if len(sys.argv) > 1 and sys.argv[1] == "read":
        from .constants import OREAD_DISABLED_MSG
        _cfg = _read_config()
        _ws_cfg = get_workspace_config(_cfg.get("default_workspace", ""))
        _oread_enabled = _ws_cfg.get(
            "runner_use_oread", _cfg.get("runner_use_oread", True),
        )
        if not _oread_enabled:
            print(OREAD_DISABLED_MSG)
            sys.exit(0)

    args = parser.parse_args()

    if args.command in ("run", "f", "exec") and shutil.which("opencode") is None:
        print(
            "Error: 'opencode' command not found on PATH. "
            "Install opencode or fix your PATH before using owrap.",
            file=sys.stderr,
        )
        sys.exit(1)

    if args.command == "p":
        from .commands.permit import PermitRunner
        PermitRunner().run()
        sys.exit(0)

    if args.command == "permit":
        from .commands.permit import PermitCmdRunner
        cmd_runner = PermitCmdRunner()
        if args.action == "status":
            cmd_runner.run_status()
        elif args.state is None:
            print("Usage: owrap permit bypass-all <on|off>")
            sys.exit(2)
        else:
            cmd_runner.run_bypass_all(args.state)
        sys.exit(0)

    if args.command == "set":
        if args.set_target == "model":
            from .commands.set_model import SetModelRunner
            SetModelRunner().run(args.slot, args.query, workspace=args.workspace)
        else:
            print("Usage: owrap set model <slot> <query> [--workspace <name>]")
            sys.exit(2)
        sys.exit(0)

    manager = Manager()
    level = "DEBUG" if getattr(args, "debug", False) else "INFO"
    logger = manager.get_logger(level=level)
    manager.set_logger(logger)
    allow_all = getattr(args, "allow_all", False)
    _base = _read_config()
    _ws_cfg = get_workspace_config(_base.get("default_workspace", ""))
    allow_all = (
        allow_all
        or _base.get("runner_allow_all", False)
        or _ws_cfg.get("runner_allow_all", False)
    )

    cmd = args.command or ""
    if cmd not in _UNLOGGED_CMDS:
        rtlog.log("cmd.start", cmd=cmd, argv=" ".join(sys.argv[1:])[:300])
    _cmd_start = time.time()
    _cmd_rc = 0
    try:
        try:
            handler = _COMMAND_HANDLERS.get(args.command)
            if handler:
                handler(args, manager, logger, allow_all)
            else:
                parser.print_help()
        except SystemExit as _e:
            _cmd_rc = _e.code if isinstance(_e.code, int) else (1 if _e.code else 0)
            raise
    finally:
        if cmd not in _UNLOGGED_CMDS:
            dur_s = round(time.time() - _cmd_start, 2)
            rtlog.log("cmd.end", cmd=cmd, rc=_cmd_rc, dur_s=dur_s)


if __name__ == "__main__":
    main()
