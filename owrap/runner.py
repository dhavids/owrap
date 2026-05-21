import argparse
import sys
from pathlib import Path

from .session import StartRunner, StopRunner, RefreshRunner, RestartRunner, CleanupRunner, EndRunner
from .commands import ExecRunner, FinishRunner, ReadRunner, RunRunner, SetupRunner, WaitRunner
from .manager import Manager
from .utils.paths import _read_config


def main():
    parser = argparse.ArgumentParser(description="OWrap Runner Utility")

    parser.add_argument("-a", "--allow-all", action="store_true", help="Pass --dangerously-skip-permissions to opencode")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    start_parser = subparsers.add_parser("start", help="Start an owrap session")
    start_parser.add_argument("research", nargs="?", default=None, help="Research project name")
    start_parser.add_argument("--shell-pid", type=int, default=None, help="Shell PID")
    start_parser.add_argument("--session-file", type=str, default=None, help="Session file path")

    stop_parser = subparsers.add_parser("stop", help="Stop an owrap session")
    stop_parser.add_argument("--session-file", type=str, default=None, help="Session file path")
    stop_parser.add_argument("--force", action="store_true", default=False, help="Kill server and clear all sessions even if others are active")

    end_parser = subparsers.add_parser("end", help="End this session only (server keeps running)")
    end_parser.add_argument("--session-file", type=str, default=None)

    refresh_parser = subparsers.add_parser("refresh", help="Refresh an owrap session")
    refresh_parser.add_argument("research", nargs="?", default=None, help="Research project name")
    refresh_parser.add_argument("--shell-pid", type=int, default=None, help="Shell PID")
    refresh_parser.add_argument("--session-file", type=str, default=None, help="Session file path")

    restart_parser = subparsers.add_parser("restart", help="Stop and restart an owrap session")
    restart_parser.add_argument("research", nargs="?", default=None, help="Research project name")
    restart_parser.add_argument("--shell-pid", type=int, default=None, help="Shell PID")
    restart_parser.add_argument("--session-file", type=str, default=None, help="Session file path")
    restart_parser.add_argument("--force", action="store_true", default=False, help="Kill server and clear all sessions before starting fresh")

    setup_parser = subparsers.add_parser("setup", help="Configure owrap for a research project")
    setup_parser.add_argument("project_root", nargs="?", default=None, help="Path to project root (where CLAUDE.md, AGENTS.md, .claude/ live)")
    setup_parser.add_argument("research_folder", nargs="?", default=None, help="Path to research folder (where self.md lives; defaults to project_root if omitted)")
    setup_parser.add_argument("--update", action="store_true", help="Check installed files against current templates and show resolved placeholder values")

    read_parser = subparsers.add_parser("read", help="Read a file via opencode")
    run_parser = subparsers.add_parser("run", help="Run a task via opencode")
    exec_parser = subparsers.add_parser("exec", aliases=["work"], help="Execute the active plan via opencode")

    stat_parser = subparsers.add_parser("stat", help="Show all active owrap sessions and server status")
    stat_parser.add_argument("filter", nargs="?", default=None, help="Filter by session_id or research name")

    cleanup_parser = subparsers.add_parser("cleanup", help="Remove stale session files and dead server state")
    cleanup_parser.add_argument("session_id", nargs="?", default=None, help="Partial session ID or filename prefix to target")

    read_parser.add_argument("-f", "--file", required=False, default=None, help="File or directory path")
    read_parser.add_argument("-g", "--grep", type=str, default=None, help="Grep pattern (fast, no opencode)")
    read_parser.add_argument("-s", "--summarise", action="store_true", help="Summarise content")
    read_parser.add_argument("-d", "--details", type=str, default=None, help="Focus details")
    read_parser.add_argument("--id", "-i", type=str, default=None, help="Read ID for parallel tracking")
    read_parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    read_parser.add_argument("-t", "--timeout", type=int, default=None, help="Timeout in seconds (default: 55)")
    read_parser.add_argument("--no-log-time", action="store_true", help="Suppress the timing block")
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
    run_parser.add_argument("--no-log-time", action="store_true", help="Suppress the timing block")

    exec_parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    exec_parser.add_argument("--no-log-time", action="store_true", help="Suppress the timing block")

    finish_parser = subparsers.add_parser("finish", help="Kill a running orun/oexec job by target (exec, task1, task2, ...)")
    finish_parser.add_argument("target", help="Job to kill: 'exec', 'task', 'task1', 'task2', 'msg1', ...")
    finish_parser.add_argument("--session", type=str, default=None, help="Session ID override")

    wait_parser = subparsers.add_parser("wait", help="Wait for task/read/msg completion")
    wait_parser.add_argument("type", choices=["run", "exec", "read", "msg", "input"])
    wait_parser.add_argument("id", nargs="?", default=None, help="ID to wait for (required for read/msg)")
    wait_parser.add_argument("--session", type=str, default=None, help="Session ID override")
    wait_parser.add_argument("--timeout", type=int, default=None, help="Timeout in seconds")

    args = parser.parse_args()

    manager = Manager()
    level = "DEBUG" if getattr(args, "debug", False) else "INFO"
    logger = manager.get_logger(level=level)
    manager.set_logger(logger)
    allow_all = getattr(args, "allow_all", False)
    allow_all = allow_all or _read_config().get("allow_all", False)

    if args.command == "start":
        StartRunner(manager, logger, allow_all=allow_all).run(
            shell_pid=args.shell_pid, session_file=args.session_file, research=args.research)
    elif args.command == "stop":
        StopRunner(manager, logger, allow_all=allow_all).run(session_file=args.session_file, force=args.force)
    elif args.command == "end":
        EndRunner(manager, logger, allow_all=allow_all).run(session_file=args.session_file)
    elif args.command == "refresh":
        RefreshRunner(manager, logger, allow_all=allow_all).run(
            shell_pid=args.shell_pid, session_file=args.session_file, research=args.research)
    elif args.command == "restart":
        RestartRunner(manager, logger, allow_all=allow_all).run(
            shell_pid=args.shell_pid, session_file=args.session_file, research=args.research, force=args.force)
    elif args.command == "setup":
        SetupRunner().run(project_root=args.project_root, research_folder=args.research_folder, update=args.update)
    elif args.command == "read":
        if getattr(args, 'list_styles', False):
            ReadRunner(manager, logger, allow_all=allow_all).list_styles()
            sys.exit(0)
        if args.file is None and args.grep is None:
            import sys as _sys; print("error: -f/--file required unless using -g/--grep", file=_sys.stderr); _sys.exit(1)
        ReadRunner(manager, logger, allow_all=allow_all).run(
            args.file, summarise=args.summarise, details=args.details,
            log_time=not args.no_log_time, grep=args.grep, read_id=getattr(args, 'id', None),
            timeout=getattr(args, 'timeout', None), verbose=args.verbose,
            prompt_style=getattr(args, 'prompt_style', None))
    elif args.command in ("run",):
        RunRunner(manager, logger, allow_all=allow_all).run(
            msg=args.msg, msg_id=getattr(args, 'id', None),
            input_path=Path(args.input) if args.input else None,
            log_time=not args.no_log_time, timeout=getattr(args, 'timeout', None))
    elif args.command in ("exec", "work"):
        ExecRunner(manager, logger, allow_all=allow_all).run(log_time=not args.no_log_time)
    elif args.command == "finish":
        FinishRunner(manager, logger, allow_all=allow_all).run(
            target=args.target,
            session_id=getattr(args, "session", None),
        )
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
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
