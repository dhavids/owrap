import argparse
import sys
from pathlib import Path

from .session import StartRunner, StopRunner, RefreshRunner, RestartRunner, CleanupRunner, EndRunner
from .commands import ExecRunner, ReadRunner, RunRunner, SetupRunner
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

    setup_parser = subparsers.add_parser("setup", help="Configure owrap for a research project")
    setup_parser.add_argument("project_root", nargs="?", default=None, help="Path to project root (where CLAUDE.md, AGENTS.md, .claude/ live)")
    setup_parser.add_argument("research_folder", nargs="?", default=None, help="Path to research folder (where self.md lives; defaults to project_root if omitted)")
    setup_parser.add_argument("--update", action="store_true", help="Check installed files against current templates and show resolved placeholder values")

    read_parser = subparsers.add_parser("read", help="Read a file via opencode")
    run_parser = subparsers.add_parser("run", help="Run a task via opencode")
    exec_parser = subparsers.add_parser("exec", aliases=["work"], help="Execute the active plan via opencode")

    stat_parser = subparsers.add_parser("stat", help="Show all active owrap sessions and server status")

    cleanup_parser = subparsers.add_parser("cleanup", help="Remove stale session files and dead server state")
    cleanup_parser.add_argument("session_id", nargs="?", default=None, help="Partial session ID or filename prefix to target")

    read_parser.add_argument("-f", "--file", required=False, default=None, help="File or directory path")
    read_parser.add_argument("-g", "--grep", type=str, default=None, help="Grep pattern (fast, no opencode)")
    read_parser.add_argument("-s", "--summarise", action="store_true", help="Summarise content")
    read_parser.add_argument("-d", "--details", type=str, default=None, help="Focus details")
    read_parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    read_parser.add_argument("--no-log-time", action="store_true", help="Suppress the timing block")

    run_parser.add_argument("--msg", type=str, default=None, help="Single-line message for task mode")
    run_parser.add_argument("--input", type=str, default=None, help="Input file path")
    run_parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    run_parser.add_argument("--no-log-time", action="store_true", help="Suppress the timing block")

    exec_parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    exec_parser.add_argument("--no-log-time", action="store_true", help="Suppress the timing block")

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
        StopRunner(manager, logger, allow_all=allow_all).run(session_file=args.session_file)
    elif args.command == "end":
        EndRunner(manager, logger, allow_all=allow_all).run(session_file=args.session_file)
    elif args.command == "refresh":
        RefreshRunner(manager, logger, allow_all=allow_all).run(
            shell_pid=args.shell_pid, session_file=args.session_file, research=args.research)
    elif args.command == "restart":
        RestartRunner(manager, logger, allow_all=allow_all).run(
            shell_pid=args.shell_pid, session_file=args.session_file, research=args.research)
    elif args.command == "setup":
        SetupRunner().run(project_root=args.project_root, research_folder=args.research_folder, update=args.update)
    elif args.command == "read":
        if args.file is None and args.grep is None:
            import sys as _sys; print("error: -f/--file required unless using -g/--grep", file=_sys.stderr); _sys.exit(1)
        ReadRunner(manager, logger, allow_all=allow_all).run(
            args.file, summarise=args.summarise, details=args.details,
            log_time=not args.no_log_time, grep=args.grep)
    elif args.command in ("run",):
        RunRunner(manager, logger, allow_all=allow_all).run(msg=args.msg, input_path=Path(args.input) if args.input else None,
                                                             log_time=not args.no_log_time)
    elif args.command in ("exec", "work"):
        ExecRunner(manager, logger, allow_all=allow_all).run(log_time=not args.no_log_time)
    elif args.command == "stat":
        from .session.stat import StatRunner
        sys.exit(StatRunner(manager, logger, allow_all).run(args))
    elif args.command == "cleanup":
        sys.exit(CleanupRunner(manager, logger, allow_all).run(args))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
