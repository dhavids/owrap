import json
import shutil
import sys
import time
from pathlib import Path

from .session import (
    StartRunner, StopRunner, RefreshRunner, RestartRunner,
    CleanupRunner, EndRunner, AttachRunner, DetachRunner,
    RestoreRunner,
)
from .commands import (
    AbortRunner, ExecRunner, ProjectRunner, ReadRunner, RunRunner,
    SetupRunner, WaitRunner,
)
from .commands.sync import SyncRunner
from .commands.daemon import DaemonRunner
from .commands.kinds import KIND_REGISTRY
from .utils.actions import dispatch, dispatch_kw
from .manager import Manager
from .utils.paths import _read_config, get_workspace_config
from .utils.arg_parser import OwrapArgumentParser
from .utils.cli_schema import SUBCOMMANDS, build_subcommand
from .utils.log import rtlog

_UNLOGGED_CMDS = {"stat", "get", "permit", "subs", "wait", "set"}


# Command Handlers

def _cmd_start(args, manager, logger, allow_all):
    if args.project_name == "daemon":
        print(dispatch_kw(KIND_REGISTRY, "daemon", "start", args))
        return
    StartRunner(manager, logger, allow_all=allow_all).run(
        shell_pid=args.shell_pid,
        session_file=args.session_file,
        project_name=args.project_name,
        session_id=getattr(args, 'session_id', None),
        subproject_name=getattr(args, 'subproject_name', None),
        project_id=getattr(args, 'project', None),
        subproject_id=getattr(args, 'subproject', None),
        repository_id=getattr(args, 'repository', None),
        repositories=getattr(args, 'repo_ids', None),
        branch_parent=getattr(args, 'branch_parent', None),
        branch_repository=getattr(args, 'branch_repository', None),
        branch_ref=getattr(args, 'branch_ref', None),
    )


def _cmd_stop(args, manager, logger, allow_all):
    target = (
        getattr(args, 'session_id', None)
        or getattr(args, 'target', None)
    )
    if target == "daemon":
        print(dispatch_kw(KIND_REGISTRY, "daemon", "stop", args))
        return
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
        project_name=args.project_name,
        session_id=getattr(args, 'session_id', None),
        subproject_name=getattr(args, 'subproject_name', None),
    )


def _cmd_attach(args, manager, logger, allow_all):
    if args.target_session_id == "repo":
        try:
            print(dispatch_kw(KIND_REGISTRY, "repository", "attach", args))
        except (OSError, ValueError, FileExistsError, FileNotFoundError) as exc:
            print(f"ERROR: {exc}")
            sys.exit(2)
        return
    AttachRunner(manager, logger, allow_all=allow_all).run(
        target_session_id=args.target_session_id,
    )


def _cmd_detach(args, manager, logger, allow_all):
    if getattr(args, "target", None) == "repo":
        try:
            print(dispatch_kw(KIND_REGISTRY, "repository", "detach", args))
        except (OSError, ValueError, FileExistsError, FileNotFoundError) as exc:
            print(f"ERROR: {exc}")
            sys.exit(2)
        return
    DetachRunner(manager, logger, allow_all=allow_all).run()


def _cmd_todo(args, manager, logger, allow_all):
    from .commands.todo import TodoRunner
    if args.target == "clear":
        TodoRunner().run_clear(args.arg2)
    elif args.target == "done":
        TodoRunner().run_done(args.arg2, args.arg3)
    elif args.target == "update":
        TodoRunner().run_update(args.arg2, args.arg3, args.arg4)
    elif args.target == "remove":
        TodoRunner().run_remove(args.arg2, args.arg3)
    else:
        TodoRunner().run(args.target, args.arg2, args.arg3)


def _cmd_decide(args, manager, logger, allow_all):
    from .commands.decide import DecideRunner
    DecideRunner().run(args.target, args.text)


def _cmd_main(args, manager, logger, allow_all):
    try:
        ProjectRunner().main()
    except (ValueError, FileNotFoundError, FileExistsError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(2)


def _cmd_sub(args, manager, logger, allow_all):
    try:
        ProjectRunner().sub(args.name, force=args.force)
    except (ValueError, FileNotFoundError, FileExistsError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(2)


def _cmd_subs(args, manager, logger, allow_all):
    try:
        ProjectRunner().subs()
    except (ValueError, FileNotFoundError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(2)


def _cmd_branch(args, manager, logger, allow_all):
    from .session.workflow import SessionWorkflow
    runner = SessionWorkflow()
    try:
        if args.name == "merge":
            if args.ref:
                raise ValueError("--ref is only valid when starting a branch")
            result = runner.merge_branch(
                args.session or "", apply=args.apply, repo_id=args.repo or "",
            )
            for repo_id, entry in result["repositories"].items():
                print(f"{repo_id}: {entry['ref']} -> {entry['base_ref']}")
                if entry["commits"]:
                    print(entry["commits"])
                if entry["stat"]:
                    print(entry["stat"])
            print("Git merge applied." if result["applied"] else
                  "Preview only. Pass --apply to merge code.")
        elif args.name == "cleanup":
            if args.ref or args.repo:
                raise ValueError("--ref and --repo are invalid for cleanup")
            if not args.session:
                raise ValueError("pass --session <child-id> after collapse")
            result = runner.cleanup_branch(args.session or "", args.apply)
            for entry in result["repositories"].values():
                print(f"Worktree: {entry['path']}")
            print("Worktrees removed." if result["applied"] else
                  "Preview only. Pass --apply to remove worktrees.")
        else:
            if args.apply or args.session or args.repo:
                raise ValueError("--apply, --session and --repo need merge or cleanup")
            data = runner.create("branch", args.name or "", args.ref or "")
            print(f"Branch session: {data['session_id']} ({data['session_name']})")
            for repo_id, entry in json.loads(
                data["branch_worktrees"]
            ).items():
                print(f"{repo_id}: {entry['path']} [{entry['ref']}]")
            print(f"__OWRAP_EXPORT__ SESSION_ID={data['session_id']}")
    except (ValueError, FileNotFoundError, FileExistsError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(2)


def _cmd_restart(args, manager, logger, allow_all):
    if args.project_name == "daemon":
        print(dispatch_kw(KIND_REGISTRY, "daemon", "restart", args))
        return
    RestartRunner(manager, logger, allow_all=allow_all).run(
        shell_pid=args.shell_pid,
        session_file=args.session_file,
        project_name=args.project_name,
        force=args.force,
        session_id=getattr(args, 'session_id', None),
    )


def _cmd_setup(args, manager, logger, allow_all):
    SetupRunner().run(
        path=args.path,
        project_name=args.name,
        workspace=args.workspace,
        docs_root=args.docs_root,
        allow_all=args.allow_all,
        oread=args.oread,
        planners=args.planners,
        executors=args.executors,
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
    from .utils.dispatch.pool import _ensure_daemon, _stop_daemon, _restart_daemon

    action = getattr(args, "action", None)
    if action == "start":
        started = _ensure_daemon()
        print("daemon: started" if started else "daemon: already running")
        return
    if action == "stop":
        stopped = _stop_daemon()
        print("daemon: stopped" if stopped else "daemon: not running")
        return
    if action == "restart":
        _restart_daemon()
        print("daemon: restarted")
        return
    DaemonRunner(manager, logger, allow_all=allow_all).run()


def _cmd_spawn(args, manager, logger, allow_all):
    from .session.workflow import SessionWorkflow
    from .utils.session.resolver import _parse, resolve
    sid, path, _ = resolve(mode="refresh")
    if not sid or not _parse(path).get("target_kind"):
        print(
            "Error: no active session with a project or repository target "
            "— run owrap start first", file=sys.stderr,
        )
        sys.exit(2)
    try:
        data = SessionWorkflow().create("spawn", args.child or "")
    except (ValueError, FileNotFoundError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(2)
    print(f"Child session: {data['session_id']} ({data['session_name']})")
    print(f"__OWRAP_EXPORT__ SESSION_ID={data['session_id']}")


def _cmd_temp(args, manager, logger, allow_all):
    from .session.workflow import SessionWorkflow
    try:
        data = SessionWorkflow().create("temp", args.name or "")
    except (ValueError, FileNotFoundError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(2)
    print(f"Temporary session: {data['session_id']} ({data['session_name']})")
    print(f"__OWRAP_EXPORT__ SESSION_ID={data['session_id']}")


def _cmd_collapse(args, manager, logger, allow_all):
    from .session.workflow import SessionWorkflow
    try:
        result = SessionWorkflow().collapse(args.session or "", args.apply)
    except (ValueError, FileNotFoundError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(2)
    print(f"Child {result['child']} -> parent {result['parent']}")
    for heading, entries in result["entries"].items():
        print(f"{heading}: {len(entries)} new entries")
        for entry in entries:
            print(f"  {entry}")
    print("Collapse applied." if result["applied"] else
          "Preview only. Pass --apply after review.")
    if result["applied"]:
        from .utils.session.resolver import attach, resolve
        current_sid, _, _ = resolve(mode="refresh")
        if current_sid == result["child"]:
            attach(result["parent"])
            print(f"__OWRAP_EXPORT__ SESSION_ID={result['parent']}")


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
    from .utils.dispatch.pool import _ensure_daemon

    config = _read_config()
    daemon_enabled = (
        config.get("owrap_runner_enabled", True)
        or config.get("owrap_context_manager_enabled", True)
    )
    if daemon_enabled:
        _ensure_daemon()
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
    sys.exit(CtxWorkerRunner().run(input_path=Path(args.input)))


def _cmd_ctx(args, manager, logger, allow_all):
    if getattr(args, "action", None) == "done":
        dispatch_kw(KIND_REGISTRY, "ctx", "done", args)
        return
    dispatch_kw(KIND_REGISTRY, "ctx", "start", args)


def _cmd_updr(args, manager, logger, allow_all):
    if args.subproject == "done":
        dispatch_kw(KIND_REGISTRY, "updr", "done", args)
        return
    dispatch_kw(KIND_REGISTRY, "updr", "start", args)


def _cmd_ctx_template(args, manager, logger, allow_all):
    from .commands.context_manager import ManualCtxRunner
    ManualCtxRunner().template(subproject=args.subproject)


def _cmd_touched(args, manager, logger, allow_all):
    from .commands.touched import TouchedRunner
    TouchedRunner().run(args.paths, note=args.note)


def _cmd_backup(args, manager, logger, allow_all):
    from .commands.backup import BackupRunner
    BackupRunner().run(args.target)


def _cmd_retrieve(args, manager, logger, allow_all):
    from .commands.backup import RetrieveRunner
    RetrieveRunner().run(args.target, timestamp=args.timestamp)


def _cmd_delete(args, manager, logger, allow_all):
    if args.what == "backup":
        from .commands.backup import DeleteBackupRunner
        DeleteBackupRunner().run(args.target, which=args.which)


def _cmd_action(action):
    """
    Build a CLI handler for a kind-dispatched action: collect the given
    arg1/arg2/arg3 (skipping ones argparse left as None), dispatch
    `action` against KIND_REGISTRY by args.kind, print what it
    returns, and turn one of its expected errors into `ERROR: ...`
    plus exit 2.
    """
    def _cmd(args, manager, logger, allow_all):
        call_args = [
            value for value in (
                getattr(args, "arg1", None), getattr(args, "arg2", None),
                getattr(args, "arg3", None),
            ) if value is not None
        ]
        try:
            message = dispatch(KIND_REGISTRY, args.kind, action, *call_args)
        except (OSError, ValueError, FileExistsError, FileNotFoundError) as exc:
            print(f"ERROR: {exc}")
            sys.exit(2)
        if message:
            print(message)
    _cmd.__name__ = f"_cmd_{action}"
    return _cmd


_cmd_update = _cmd_action("update")
_cmd_add = _cmd_action("add")
_cmd_remove = _cmd_action("remove")
_cmd_clear = _cmd_action("clear")
_cmd_done = _cmd_action("done")


def _cmd_get(args, manager, logger, allow_all):
    from .commands.get import GetRunner
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
    if args.what == "history":
        # Alias: `owrap get history [N]` == `owrap get runtime history [N]`.
        count = int(args.kind) if args.kind is not None else args.count
        sys.exit(runner.run_runtime_history(count=count, sid=args.sid) or 0)
    if args.what == "runtime":
        if args.kind == "history":
            sys.exit(runner.run_runtime_history(
                count=args.count, sid=args.sid,
            ) or 0)
        sys.exit(runner.run_runtime(
            tail=args.tail, ev_prefix=args.ev, sid=args.sid,
        ) or 0)
    if args.what == "transcript":
        sys.exit(runner.run_transcript(
            session_id=args.session, ccsid=args.ccsid,
        ) or 0)
    sys.exit(runner.run(args.what, session_id=args.session,
                        dispatch_id=args.id, kind=args.kind) or 0)


_COMMAND_HANDLERS = {
    "start": _cmd_start,
    "stop": _cmd_stop,
    "end": _cmd_end,
    "refresh": _cmd_refresh,
    "attach": _cmd_attach,
    "detach": _cmd_detach,
    "todo": _cmd_todo,
    "decide": _cmd_decide,
    "main": _cmd_main,
    "sub": _cmd_sub,
    "subs": _cmd_subs,
    "branch": _cmd_branch,
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
    "spawn": _cmd_spawn,
    "temp": _cmd_temp,
    "collapse": _cmd_collapse,
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
    "ctx-template": _cmd_ctx_template,
    "touched": _cmd_touched,
    "backup": _cmd_backup,
    "retrieve": _cmd_retrieve,
    "delete": _cmd_delete,
    "update": _cmd_update,
    "rename": _cmd_update,
    "add": _cmd_add,
    "remove": _cmd_remove,
    "clear": _cmd_clear,
    "done": _cmd_done,
    "get": _cmd_get,
}


def _build_parser():
    """
    Construct the top-level argparse parser and every subcommand parser
    from the declarative schema in `utils/cli_schema.py`.
    """
    parser = OwrapArgumentParser(
        description="OWrap Runner Utility", prog="owrap",
    )

    parser.add_argument(
        "-a", "--allow-all", action="store_true",
        help="Pass --dangerously-skip-permissions to opencode",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    for spec in SUBCOMMANDS:
        build_subcommand(subparsers, spec)

    return parser


def main():
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

    parser = _build_parser()
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
        PermitRunner().run(workspace_name=args.workspace)
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
