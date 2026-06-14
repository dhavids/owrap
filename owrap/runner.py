import argparse
import sys
from pathlib import Path

from .session import StartRunner, StopRunner, RefreshRunner, RestartRunner, CleanupRunner, EndRunner, AttachRunner, UpdateAreaRunner
from .commands import ExecRunner, FinishRunner, ReadRunner, RunRunner, SetupRunner, WaitRunner
from .commands.sync_cmd import SyncRunner
from .commands.keepalive import KeepaliveRunner
from .manager import Manager
from .utils.paths import _read_config, get_workspace_config


def main():
    parser = argparse.ArgumentParser(description="OWrap Runner Utility")

    parser.add_argument("-a", "--allow-all", action="store_true", help="Pass --dangerously-skip-permissions to opencode")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    start_parser = subparsers.add_parser("start", help="Start an owrap session")
    start_parser.add_argument("research", nargs="?", default=None, help="Research project name")
    start_parser.add_argument("--shell-pid", type=int, default=None, help="Shell PID")
    start_parser.add_argument("--session-file", type=str, default=None, help="Session file path")
    start_parser.add_argument("-i", "--session-id", type=str, default=None, help="Session ID: attach if exists, create with this ID if not")
    start_parser.add_argument("area", nargs="?", default=None, help="Area within research (e.g. self-translator)")

    stop_parser = subparsers.add_parser("stop", help="Stop an owrap session")
    stop_parser.add_argument("target", nargs="?", default=None, help="Session ID prefix or research name to stop (alias for -i/--session-id)")
    stop_parser.add_argument("-i", "--session-id", type=str, default=None, help="Session ID or research name to stop (alias for positional target)")
    stop_parser.add_argument("--session-file", type=str, default=None, help="Session file path")
    stop_parser.add_argument("--force", action="store_true", default=False, help="Kill server and clear all sessions even if others are active")

    end_parser = subparsers.add_parser("end", help="End this session only (server keeps running)")
    end_parser.add_argument("target", nargs="?", default=None, help="Session ID prefix or research name to end (alias for -i/--session-id)")
    end_parser.add_argument("-i", "--session-id", type=str, default=None, help="Session ID or research name to end (alias for positional target)")
    end_parser.add_argument("--session-file", type=str, default=None)

    refresh_parser = subparsers.add_parser("refresh", help="Refresh an owrap session")
    refresh_parser.add_argument("research", nargs="?", default=None, help="Research project name")
    refresh_parser.add_argument("--shell-pid", type=int, default=None, help="Shell PID")
    refresh_parser.add_argument("--session-file", type=str, default=None, help="Session file path")
    refresh_parser.add_argument("-i", "--session-id", type=str, default=None, help="Session ID to refresh (skips env resolution)")
    refresh_parser.add_argument("area", nargs="?", default=None, help="Update area for this session")

    attach_parser = subparsers.add_parser("attach", help="Bind an existing session to this Claude window")
    attach_parser.add_argument("target_session_id", help="Session ID to attach to")
    attach_parser.add_argument("--shell-pid", type=int, default=None, help="Shell PID (ignored)")

    restart_parser = subparsers.add_parser("restart", help="Stop and restart an owrap session")
    restart_parser.add_argument("research", nargs="?", default=None, help="Research project name")
    restart_parser.add_argument("--shell-pid", type=int, default=None, help="Shell PID")
    restart_parser.add_argument("--session-file", type=str, default=None, help="Session file path")
    restart_parser.add_argument("--force", action="store_true", default=False, help="Kill server and clear all sessions before starting fresh")
    restart_parser.add_argument("-i", "--session-id", type=str, default=None, help="Session ID to restart")

    setup_parser = subparsers.add_parser("setup", help="Configure owrap for a workspace")
    setup_parser.add_argument("path", nargs="?", default=None, help="Path to workspace directory (derives name from basename)")
    setup_parser.add_argument("--name", type=str, default=None, help="Workspace name (explicit override)")
    setup_parser.add_argument("--workspace", type=str, default=None, help="Path to workspace (used with --name for explicit override)")
    setup_parser.add_argument("--research-root", type=str, default=None, help="Path to research root")
    setup_parser.add_argument("--allow-all", action="store_true", default=None, help="Allow all permissions")
    setup_parser.add_argument("--oread", action="store_true", default=None, help="Use oread for all file reads")
    setup_parser.add_argument("--no-oread", dest="oread", action="store_false", help="Do not use oread for file reads")

    sync_parser = subparsers.add_parser("sync", help="Re-apply staged templates to project files")

    read_parser = subparsers.add_parser("read", help="Read a file via opencode")
    run_parser = subparsers.add_parser("run", help="Run a task via opencode")
    exec_parser = subparsers.add_parser("exec", aliases=["work"], help="Execute the active plan via opencode")

    stat_parser = subparsers.add_parser("stat", help="Show all active owrap sessions and server status")
    stat_parser.add_argument("filter", nargs="?", default=None, help="Filter by session_id or research name")

    cleanup_parser = subparsers.add_parser("cleanup", help="Remove stale session files and dead server state")
    cleanup_parser.add_argument("session_id", nargs="?", default=None, help="Partial session ID or filename prefix to target")

    read_parser.add_argument("-f", "--file", nargs="+", required=False, default=None, dest="files", help="File or directory path (repeatable for -g grep)")
    read_parser.add_argument("-g", "--grep", type=str, default=None, help="Grep pattern (fast, no opencode)")
    read_parser.add_argument("-s", "--summarise", action="store_true", help="Summarise content")
    read_parser.add_argument("-d", "--details", type=str, default=None, help="Focus details")
    read_parser.add_argument("--id", "-i", type=str, default=None, help="Read ID for parallel tracking")
    read_parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    read_parser.add_argument("-t", "--timeout", type=int, default=None, help="Timeout in seconds (default: 55)")
    read_parser.add_argument("--log-time", action="store_true", help="Show the [timing] block (debugging/tests only)")
    read_parser.add_argument("-v", "--verbose", action="store_true", default=False, help="Full cat: bypass the 100-line limit")
    read_parser.add_argument("--list-styles", action="store_true", default=False,
                             help="List all prompt styles and file-type extension defaults")
    read_parser.add_argument("-p", "--prompt-style", type=str, default=None,
                             help="Summary prompt style: default, terse, structured, code, exec, bullets")

    run_parser.add_argument("--msg", type=str, default=None, help="Single-line message for task mode")
    run_parser.add_argument("--id", "-i", type=str, default=None, help="Msg ID for parallel tracking")
    run_parser.add_argument("--input", type=str, default=None, help="Input file path")
    run_parser.add_argument("-t", "--timeout", type=int, default=None, help="Timeout in seconds (default: 180 for --msg)")
    run_parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    run_parser.add_argument("--log-time", action="store_true", help="Show the [timing] block (debugging/tests only)")
    run_parser.add_argument("--no-context", action="store_true", help="Suppress inline context header")
    run_parser.add_argument("--model", "-m", type=str, default=None, help="Model override")

    exec_parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    exec_parser.add_argument("--log-time", action="store_true", help="Show the [timing] block (debugging/tests only)")

    finish_parser = subparsers.add_parser("finish", help="Kill a running orun/oexec job by target (exec, task1, task2, ...)")
    finish_parser.add_argument("target", help="Job to kill: 'exec', 'task', 'task1', 'task2', 'msg1', ...")
    finish_parser.add_argument("--session", type=str, default=None, help="Session ID override")

    subparsers.add_parser("trim", help="Kill all live servers with no active sessions")

    killservers_parser = subparsers.add_parser("killservers", help="Kill all servers and running tasks without clearing session/context state")
    killservers_parser.add_argument("--session", type=str, default=None, help="Limit to a specific session ID")

    fallback_parser = subparsers.add_parser("f", help="Run a fallback --execf/--taskf invocation directly (no server); mode inferred from filename")
    fallback_parser.add_argument("path", help="Path to a plan or task .md file, or 'tstop'/'estop' to stop a running task/exec fallback")

    update_area_parser = subparsers.add_parser("update-area", help="Set research and area for the current session")
    update_area_parser.add_argument("research", help="Research name")
    update_area_parser.add_argument("area", help="Area within research (e.g. self-translator)")

    precompact_parser = subparsers.add_parser("precompact", help="PreCompact hook handler")

    precompact_worker_parser = subparsers.add_parser("precompact-worker", help="PreCompact worker")
    precompact_worker_parser.add_argument("--input", type=str, required=True, help="Input JSON path")

    get_parser = subparsers.add_parser("get", help="Inspect session files")
    get_parser.add_argument("what", choices=["plan", "input", "context", "session", "memory", "project", "area", "research", "config"])
    get_parser.add_argument("--session", default=None)

    keepalive_parser = subparsers.add_parser("keepalive", help="Run the keepalive daemon")

    wait_parser = subparsers.add_parser("wait", help="Wait for task/read/msg completion")
    wait_parser.add_argument("type", choices=["run", "exec", "read", "msg", "input"])
    wait_parser.add_argument("id", nargs="?", default=None, help="ID to wait for (required for read/msg)")
    wait_parser.add_argument("--session", type=str, default=None, help="Session ID override")
    wait_parser.add_argument("--timeout", type=int, default=None, help="Timeout in seconds")

    if len(sys.argv) > 1 and sys.argv[1] == "read":
        from .constants import OREAD_DISABLED_MSG
        _cfg = _read_config()
        _ws_cfg = get_workspace_config(_cfg.get("default_workspace", ""))
        _oread_enabled = _ws_cfg.get("oread", _cfg.get("oread", True))
        if not _oread_enabled:
            print(OREAD_DISABLED_MSG)
            sys.exit(0)

    args = parser.parse_args()

    manager = Manager()
    level = "DEBUG" if getattr(args, "debug", False) else "INFO"
    logger = manager.get_logger(level=level)
    manager.set_logger(logger)
    allow_all = getattr(args, "allow_all", False)
    _base = _read_config()
    _ws_cfg = get_workspace_config(_base.get("default_workspace", ""))
    allow_all = allow_all or _base.get("allow_all", False) or _ws_cfg.get("allow_all", False)

    if args.command == "start":
        StartRunner(manager, logger, allow_all=allow_all).run(
            shell_pid=args.shell_pid, session_file=args.session_file, research=args.research,
            session_id=getattr(args, 'session_id', None), area=getattr(args, 'area', None))
    elif args.command == "stop":
        target = getattr(args, 'session_id', None) or getattr(args, 'target', None)
        StopRunner(manager, logger, allow_all=allow_all).run(session_file=args.session_file, force=args.force, target=target)
    elif args.command == "end":
        target = getattr(args, 'session_id', None) or getattr(args, 'target', None)
        EndRunner(manager, logger, allow_all=allow_all).run(session_file=args.session_file, target=target)
    elif args.command == "refresh":
        RefreshRunner(manager, logger, allow_all=allow_all).run(
            shell_pid=args.shell_pid, session_file=args.session_file, research=args.research,
            session_id=getattr(args, 'session_id', None), area=getattr(args, 'area', None))
    elif args.command == "attach":
        AttachRunner(manager, logger, allow_all=allow_all).run(target_session_id=args.target_session_id)
    elif args.command == "restart":
        RestartRunner(manager, logger, allow_all=allow_all).run(
            shell_pid=args.shell_pid, session_file=args.session_file, research=args.research, force=args.force,
            session_id=getattr(args, 'session_id', None))
    elif args.command == "setup":
        SetupRunner().run(path=args.path, project_name=args.name, workspace=args.workspace, research_root=args.research_root, allow_all=args.allow_all, oread=args.oread)
    elif args.command == "sync":
        SyncRunner().run()
    elif args.command == "read":
        if getattr(args, 'list_styles', False):
            ReadRunner(manager, logger, allow_all=allow_all).list_styles()
            sys.exit(0)
        if args.files is None and args.grep is None:
            import sys as _sys; print("error: -f/--file required unless using -g/--grep", file=_sys.stderr); _sys.exit(1)
        ReadRunner(manager, logger, allow_all=allow_all).run(
            args.files[0] if args.files and len(args.files)==1 else args.files, summarise=args.summarise, details=args.details,
            log_time=args.log_time, grep=args.grep, read_id=getattr(args, 'id', None),
            timeout=getattr(args, 'timeout', None), verbose=args.verbose,
            prompt_style=getattr(args, 'prompt_style', None))
    elif args.command in ("run",):
        RunRunner(manager, logger, allow_all=allow_all, no_context=args.no_context, model=args.model).run(
            msg=args.msg, msg_id=getattr(args, 'id', None),
            input_path=Path(args.input) if args.input else None,
            log_time=args.log_time, timeout=getattr(args, 'timeout', None))
    elif args.command in ("exec", "work"):
        ExecRunner(manager, logger, allow_all=allow_all).run(log_time=args.log_time)
    elif args.command == "finish":
        FinishRunner(manager, logger, allow_all=allow_all).run(
            target=args.target,
            session_id=getattr(args, "session", None),
        )
    elif args.command == "trim":
        Manager.trim_idle_servers()
    elif args.command == "killservers":
        from .session.stop import KillServersRunner
        KillServersRunner().run(session_id=getattr(args, "session", None))
    elif args.command == "keepalive":
        KeepaliveRunner(manager, logger, allow_all=allow_all).run()
    elif args.command == "update-area":
        UpdateAreaRunner(manager, logger, allow_all=allow_all).run(research=args.research, area=args.area)
    elif args.command == "wait":
        WaitRunner(manager, logger, allow_all=allow_all).run(
            wait_type=args.type,
            wait_id=args.id,
            session_id=args.session,
            timeout=args.timeout,
        )
    elif args.command == "stat":
        from .session.stat import StatRunner
        sys.exit(StatRunner(manager, logger, allow_all).run(args))
    elif args.command == "cleanup":
        sys.exit(CleanupRunner(manager, logger, allow_all).run(args))
    elif args.command == "f":
        from .commands.fallback import FallbackRunner
        FallbackRunner().run(args.path)
    elif args.command == "precompact":
        from .commands.precompact import PrecompactRunner
        PrecompactRunner().run()
    elif args.command == "precompact-worker":
        from .commands.precompact import PrecompactWorkerRunner
        PrecompactWorkerRunner().run(input_path=Path(args.input))
    elif args.command == "get":
        from .commands.get_cmd import GetRunner
        sys.exit(GetRunner().run(args.what, session_id=args.session) or 0)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
