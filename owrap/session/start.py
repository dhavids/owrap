import os
import shutil
import sys
import time
from pathlib import Path

from ..base import BaseRunner
from ..manager import Manager
from ..utils.paths import SESSION_DIR, SESSIONS_DIR, SERVER_LOGS_DIR
from ..utils.paths import (
    get_plan_path, session_input,
    _read_config, context_path, get_workspace_config,
)
from ..utils.paths import (
    session_dir, session_tasks_dir, session_msg_output_dir,
    session_task_output_dir,
)
from ..utils.session.resolver import (
    resolve, update_session_field, migrate_legacy_files,
    session_file as _sf, ccsid_pointer, _write as _sr_write,
    BY_CCSID_DIR, BY_OPENCODE_RUN_ID_DIR,
    BY_CODEX_SESSION_ID_DIR, codex_session_id_pointer,
    list_sessions, _parse, attach, mint_session_id,
    opencode_run_id_pointer, _clear_anchor, resolve_session_or_exit,
    detach, attached_ccsids, print_known_sessions, set_session_identity,
)
from ..utils.log.retention import prune_server_logs
from ..utils.memory.records import ensure_project_exists, resolve_memory_target
from .orientation import print_orientation
from .stop import StopRunner


def _orientation_target(session_id):
    data = _parse(_sf(session_id))
    if not data.get("target_kind"):
        return None
    try:
        return resolve_memory_target(data, allow_missing=True)
    except (OSError, ValueError):
        return None


def _mint_from(old_sid, parent_sid=None):
    """
    Detach the current window, mint a session, and write fresh pointers.

    Return the new session ID and path.
    """
    _clear_anchor(old_sid, BY_CCSID_DIR)
    _clear_anchor(old_sid, BY_OPENCODE_RUN_ID_DIR)
    _clear_anchor(old_sid, BY_CODEX_SESSION_ID_DIR)
    ccsid_env = os.environ.get(
        "CLAUDE_CODE_SESSION_ID", "",
    ).strip()
    oid_env = os.environ.get(
        "OPENCODE_RUN_ID", "",
    ).strip()
    cid_env = os.environ.get("CODEX_SESSION_ID", "").strip()
    new_sid = mint_session_id()
    new_path = _sf(new_sid)
    data = {
        "session_id": new_sid,
        "claude_session_id": ccsid_env,
        "opencode_run_id": oid_env,
        "codex_session_id": cid_env,
        "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    if parent_sid is not None:
        data["parent_session_id"] = parent_sid
    _sr_write(new_path, data)
    if ccsid_env:
        BY_CCSID_DIR.mkdir(parents=True, exist_ok=True)
        ccsid_pointer(ccsid_env).write_text(new_sid)
    if oid_env:
        BY_OPENCODE_RUN_ID_DIR.mkdir(
            parents=True, exist_ok=True,
        )
        opencode_run_id_pointer(oid_env).write_text(new_sid)
    if cid_env:
        BY_CODEX_SESSION_ID_DIR.mkdir(parents=True, exist_ok=True)
        codex_session_id_pointer(cid_env).write_text(new_sid)
    return new_sid, new_path


class StartRunner(BaseRunner):
    """
    Initialize a new owrap session, resolve workspace, and print orientation.
    """

    def run(self, shell_pid=None, session_file=None, project_name=None,
            session_id=None, subproject_name=None, project_id=None,
            subproject_id=None, repository_id=None, repositories=None,
            branch_parent=None, branch_repository=None, branch_ref=None):
        """
        Execute the start workflow: resolve session, ensure server,
        populate context, and exit.
        """
        if project_name and (project_id or repository_id):
            print(
                "Error: a bare project name conflicts with --project/"
                "--repository — use one or the other", file=sys.stderr,
            )
            sys.exit(2)
        if project_name:
            # A bare name with no --project/--repository is always a project id.
            project_id = project_name
            subproject_id = subproject_name or subproject_id
        has_identity = project_id or repository_id
        if (subproject_id or branch_parent or branch_repository or
                branch_ref or repositories) and not has_identity:
            print(
                "Error: explicit identity fields require --project or "
                "--repository", file=sys.stderr,
            )
            sys.exit(2)
        migrate_legacy_files()

        is_new_session = False
        if session_id is not None:
            sf_path = _sf(session_id)
            if sf_path.exists():
                session_path = sf_path
            else:
                is_new_session = True
                ccsid = os.environ.get("CLAUDE_CODE_SESSION_ID", "").strip()
                cid = os.environ.get("CODEX_SESSION_ID", "").strip()
                _sr_write(sf_path, {
                    "session_id": session_id,
                    "claude_session_id": ccsid,
                    "codex_session_id": cid,
                    "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
                })
                if ccsid:
                    BY_CCSID_DIR.mkdir(parents=True, exist_ok=True)
                    ccsid_pointer(ccsid).write_text(session_id)
                if cid:
                    BY_CODEX_SESSION_ID_DIR.mkdir(parents=True, exist_ok=True)
                    codex_session_id_pointer(cid).write_text(session_id)
                session_path = sf_path
        else:
            session_id, session_path, source = resolve(mode="start")
            if source != "minted" and project_id:
                existing = _parse(session_path)
                if (
                    existing.get("project_id") or existing.get("repository_id")
                ) and existing.get("project_id") != project_id:
                    session_id, session_path = _mint_from(session_id)
                    source = "minted"
            is_new_session = (source == "minted")

        base = _read_config()
        workspace_name = base.get("default_workspace", "")

        if project_id or repository_id:
            try:
                if (
                    get_workspace_config(workspace_name).get("docs_root")
                    or get_workspace_config(workspace_name).get("research_root")
                    or base.get("docs_root") or base.get("research_root")
                ):
                    if project_id:
                        ensure_project_exists(
                            workspace_name, project_id, subproject_id or "",
                        )
                    candidate = {
                        "target_kind": "project" if project_id else "repository",
                        "project_id": project_id or "",
                        "subproject_id": subproject_id or "",
                        "repository_id": repository_id or "",
                        "workspace": workspace_name,
                    }
                    record_target = resolve_memory_target(
                        candidate, allow_missing=True,
                    )
                    if project_id and repositories is None:
                        repositories = list(record_target.repository_ids)
                    if record_target.branch_parent:
                        for field, supplied in (
                            ("branch_parent", branch_parent),
                            ("branch_repository", branch_repository),
                            ("branch_ref", branch_ref),
                        ):
                            expected = getattr(record_target, field)
                            if supplied and supplied != expected:
                                raise ValueError(
                                    f"{field} disagrees with project record"
                                )
                        branch_parent = branch_parent or record_target.branch_parent
                        branch_repository = (
                            branch_repository or record_target.branch_repository
                        )
                        branch_ref = branch_ref or record_target.branch_ref
                set_session_identity(
                    session_id, project_id=project_id,
                    subproject_id=subproject_id,
                    repository_id=repository_id,
                    repositories=repositories,
                    branch_parent=branch_parent,
                    branch_repository=branch_repository,
                    branch_ref=branch_ref,
                )
            except (ValueError, FileNotFoundError, FileExistsError) as exc:
                print(f"Error: {exc}", file=sys.stderr)
                sys.exit(2)
        if repository_id or project_id:
            for field in ("research", "area", "child"):
                update_session_field(session_id, field, "")

        from ..utils.dispatch.pool import _pool_active, ensure_min_servers, _ensure_daemon
        if _pool_active():
            ensure_min_servers()
            _ensure_daemon()
        else:
            Manager().ensure_running()

        if workspace_name:
            update_session_field(session_id, "workspace", workspace_name)

        prune_server_logs(SESSION_DIR, SERVER_LOGS_DIR)

        session_dir(session_id).mkdir(parents=True, exist_ok=True)
        (session_dir(session_id) / "exec").mkdir(parents=True, exist_ok=True)
        (session_dir(session_id) / "run").mkdir(parents=True, exist_ok=True)
        session_tasks_dir(session_id).mkdir(parents=True, exist_ok=True)
        session_msg_output_dir(session_id).mkdir(parents=True, exist_ok=True)
        session_task_output_dir(session_id).mkdir(parents=True, exist_ok=True)

        _old_docs = Path(__file__).resolve().parents[2] / "docs"
        _new_docs = SESSION_DIR / "docs"
        if _old_docs.exists() and any(_old_docs.iterdir()):
            _new_docs.mkdir(parents=True, exist_ok=True)
            shutil.copytree(str(_old_docs), str(_new_docs), dirs_exist_ok=True)
            shutil.rmtree(str(_old_docs))
            print(f"  [owrap] Migrated {_old_docs} -> {_new_docs}")

        plan_path = get_plan_path(session_id)
        input_path = session_input(session_id)

        self.manager.session_id = session_id
        self.manager.create_context()
        self.manager._housekeeping()
        self.manager.refresh_context_plan(plan_path)
        self.manager.start_watchdog()

        if self.logger:
            self.logger.info(
                "start session=%s project_id=%s", session_id, project_id or "none",
            )
        cp = context_path(session_id)
        print_orientation(
            session_id, plan_path=plan_path,
            input_path=input_path, context_path=cp,
            runner_enabled=_read_config().get("owrap_runner_enabled", True),
            target=_orientation_target(session_id),
        )
        print(f"\n__OWRAP_EXPORT__ SESSION_ID={session_id}")
        sys.exit(0)


class RefreshRunner(BaseRunner):
    """
    Refresh an existing owrap session's context and re-print orientation.
    """

    def run(self, shell_pid=None, session_file=None, project_name=None,
            session_id=None, subproject_name=None):
        """
        Execute the refresh workflow: validate session, update context, and exit.
        """
        if session_id is not None:
            session_path = _sf(session_id)
            if not session_path.exists():
                print(f"ERROR: session '{session_id}' not found. "
                      "Use 'owrap stat' to list sessions.")
                sys.exit(2)
        else:
            session_id, session_path, source = resolve(mode="refresh")
            if session_id is None:
                print("ERROR: cannot refresh — no SESSION_ID in env and "
                      "no Claude session anchor matched.")
                print()
                print("Known sessions:")
                for s in list_sessions():
                    ccsid_val = s.get("claude_session_id", "-")
                    _cc = ccsid_val[:8] if ccsid_val != "-" else "-"
                    print(
                        f"  {s['session_id']}  project={s.get('project_id','-')}  "
                        f"started={s.get('started','-')}  ccsid={_cc}",
                    )
                print()
                print("Either: export SESSION_ID=<id>  OR  "
                      "~/bin/owrap attach <id>  OR  ~/bin/owrap start <name>")
                sys.exit(2)

        data = _parse(session_path)
        existing_project_name = data.get("project_id") or None
        existing_subproject_name = data.get("subproject_id") or None
        if project_name is None:
            project_name = existing_project_name

        from ..utils.dispatch.pool import _pool_active, ensure_min_servers, _ensure_daemon
        if _pool_active():
            ensure_min_servers()
            _ensure_daemon()
        else:
            url = self.manager.ensure_running()
            if url is None:
                if data.get("session_mode") == "temp":
                    print("ERROR: cannot start a server for this temp session.")
                    sys.exit(2)
                os.environ["SESSION_ID"] = session_id
                StartRunner(self.manager).run(
                    shell_pid=shell_pid, project_name=project_name,
                )
                return

        if project_name is not None and project_name != existing_project_name:
            if data.get("target_kind") == "repository":
                print(
                    "Error: a repository-only session cannot also name a "
                    "project", file=sys.stderr,
                )
                sys.exit(2)
            subproject_id = (
                subproject_name if subproject_name is not None
                else data.get("subproject_id", "")
            )
            workspace_name = data.get("workspace", "")
            try:
                ensure_project_exists(workspace_name, project_name, subproject_id)
                target = resolve_memory_target({
                    **data, "target_kind": "project", "project_id": project_name,
                    "subproject_id": subproject_id,
                })
            except (OSError, ValueError, FileExistsError) as exc:
                print(f"ERROR: {exc}")
                sys.exit(2)
            set_session_identity(
                session_id, project_id=project_name, subproject_id=subproject_id,
                repositories=list(target.repository_ids),
                branch_parent=target.branch_parent,
                branch_repository=target.branch_repository,
                branch_ref=target.branch_ref,
            )
            for field in ("research", "area", "child"):
                update_session_field(session_id, field, "")
            subproject_name = subproject_id
        elif subproject_name is not None:
            update_session_field(session_id, "subproject_id", subproject_name)

        self.manager._housekeeping()

        plan_path = get_plan_path(session_id)
        input_path = session_input(session_id)

        if self.logger:
            self.logger.info(
                "refresh session=%s project_id=%s", session_id,
                project_name or "none",
            )
        cp = context_path(session_id)
        print_orientation(
            session_id, plan_path=plan_path,
            input_path=input_path, context_path=cp,
            runner_enabled=_read_config().get("owrap_runner_enabled", True),
            target=_orientation_target(session_id),
        )
        update_session_field(
            session_id, "last_refresh", time.strftime("%Y-%m-%dT%H:%M:%S"),
        )
        print(f"\n__OWRAP_EXPORT__ SESSION_ID={session_id}")
        sys.exit(0)


class AttachRunner(BaseRunner):
    """
    Attach to an existing owrap session by ID and print orientation.
    """

    def run(self, target_session_id=None):
        """
        Attach to the given session id, project id, or repository id, and
        re-export its environment variables.
        """
        if not target_session_id:
            print(
                "ERROR: owrap attach <session_id|project|repository> — "
                "missing target.",
            )
            print()
            print_known_sessions()
            sys.exit(2)

        resolved_sid = resolve_session_or_exit(
            target_session_id, print_known_on_none=True,
        )

        try:
            sid, sf, prev = attach(resolved_sid)
        except (FileNotFoundError, RuntimeError) as e:
            print(f"ERROR: {e}")
            sys.exit(2)

        data = _parse(sf)
        url = data.get("server_url", "")
        if data.get("target_kind"):
            for field in ("research", "area", "child"):
                update_session_field(sid, field, "")

        plan_path = get_plan_path(sid)
        input_path = session_input(sid)
        cp = context_path(sid)

        self.manager.session_id = sid
        print(
            f"ATTACHED session={sid}  "
            f"prev_session_for_this_window={prev or '-'}",
        )
        print_orientation(
            sid, url, plan_path, input_path,
            context_path=cp, attach=True,
            runner_enabled=_read_config().get("owrap_runner_enabled", True),
            target=_orientation_target(sid),
        )
        print(f"\n__OWRAP_EXPORT__ SESSION_ID={sid}")
        sys.exit(0)


class DetachRunner(BaseRunner):
    """
    Release this window's attachment to whatever session it is bound to.
    """

    def run(self):
        """
        Detach the current ccsid/oid from its session without affecting
        any other window still attached to it.
        """
        window_id = (
            os.environ.get("CLAUDE_CODE_SESSION_ID", "").strip()
            or os.environ.get("CODEX_SESSION_ID", "").strip()
        )
        sid = detach()
        if not sid:
            print("Not attached to any session")
            sys.exit(1)

        from ..commands.context_manager import prune_ctx_state_window
        prune_ctx_state_window(sid, window_id)

        remaining = len(attached_ccsids(sid))
        print(f"DETACHED session={sid}  still_attached={remaining}")
        sys.exit(0)


class RestartRunner(BaseRunner):
    """
    Stop and immediately re-start an owrap session.
    """

    def run(self, shell_pid=None, session_file=None, project_name=None,
            force=False, session_id=None):
        """
        Stop the current session and start a fresh one with the same parameters.
        """
        if self.logger:
            self.logger.info(
                "restart initiated project_id=%s force=%s session_id=%s",
                project_name or "none", force, session_id or "none",
            )
        StopRunner(self.manager, self.logger).run(
            no_exit=True, force=force, target=session_id,
        )
        StartRunner(
            self.manager, self.logger, allow_all=self.allow_all,
        ).run(
            shell_pid=shell_pid, session_file=session_file,
            project_name=project_name, session_id=session_id,
        )


