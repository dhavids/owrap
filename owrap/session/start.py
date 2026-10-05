import argparse
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

from ..base import BaseRunner
from ..manager import Manager
from ..utils.paths import SESSION_DIR, SESSIONS_DIR, SERVER_LOGS_DIR
from ..utils.paths import (
    get_plan_path, get_project_file_path, get_todo_file_path, session_input,
    _read_config, context_path, get_workspace_config,
    resolve_memory_project_paths,
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
from ..utils.memory.records import resolve_memory_target
from .orientation import print_orientation
from .stop import StopRunner


def _todo_path_or_none(research):
    """
    Return the per-research todo file path, or None if research/research_root
    isn't configured.
    """
    if not research:
        return None
    try:
        return get_todo_file_path(research)
    except ValueError:
        return None


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

    def run(self, shell_pid=None, session_file=None, research=None,
            session_id=None, area=None, child=None, project_id=None,
            subproject_id=None, repository_id=None, repositories=None,
            branch_parent=None, branch_repository=None, branch_ref=None):
        """
        Execute the start workflow: resolve session, ensure server,
        populate context, and exit."""
        if research is None and not (project_id or repository_id):
            research = _read_config().get("default_research")
        if (project_id or repository_id) and child:
            print(
                "Error: --child uses legacy areas; use --subproject "
                "for an explicit target", file=sys.stderr,
            )
            sys.exit(2)
        has_identity = project_id or repository_id
        if (subproject_id or branch_parent or branch_repository or
                branch_ref or repositories) and not has_identity:
            print(
                "Error: explicit identity fields require --project or "
                "--repository", file=sys.stderr,
            )
            sys.exit(2)
        if repository_id and research:
            print(
                "Error: a repository-only session cannot also name a "
                "research project", file=sys.stderr,
            )
            sys.exit(2)
        if child:
            if not area:
                print("Error: a child suffix requires an area to be "
                      "given too", file=sys.stderr)
                sys.exit(1)
            area = f"{area}-{child}"
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
        elif child:
            parent_sid, parent_path, _ = resolve(mode="start")
            session_id, session_path = _mint_from(
                parent_sid, parent_sid,
            )
            is_new_session = True
        else:
            session_id, session_path, source = resolve(mode="start")
            if source != "minted" and research:
                existing_research = _parse(session_path).get("research")
                if existing_research and existing_research != research:
                    session_id, session_path = _mint_from(session_id)
                    source = "minted"
            is_new_session = (source == "minted")

        base = _read_config()
        workspace_name = research or base.get("default_workspace", "")
        if (
            workspace_name != base.get("default_workspace", "")
            and not get_workspace_config(workspace_name)
        ):
            workspace_name = base.get("default_workspace", workspace_name)

        if project_id or repository_id:
            try:
                if (
                    get_workspace_config(workspace_name).get("docs_root")
                    or get_workspace_config(workspace_name).get("research_root")
                    or base.get("docs_root") or base.get("research_root")
                ):
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
            except (ValueError, FileNotFoundError) as exc:
                print(f"Error: {exc}", file=sys.stderr)
                sys.exit(2)
        if repository_id:
            for field in ("research", "area", "child"):
                update_session_field(session_id, field, "")

        from ..utils.dispatch.pool import _pool_active, ensure_min_servers, _ensure_daemon
        if _pool_active():
            ensure_min_servers()
            _ensure_daemon()
        else:
            Manager().ensure_running()

        if research:
            update_session_field(session_id, "research", research)
        if area:
            update_session_field(session_id, "area", area)
        elif is_new_session and not has_identity:
            # Default to "main" so Update Protocol/donow area checks have a target.
            area = "main"
            update_session_field(session_id, "area", area)
        if child:
            update_session_field(session_id, "child", child)

        # Resolve workspace name: explicit research -> use as workspace
        # key, else default_workspace
        if workspace_name:
            update_session_field(session_id, "workspace", workspace_name)

        prune_server_logs(SESSION_DIR, SERVER_LOGS_DIR)

        session_dir(session_id).mkdir(parents=True, exist_ok=True)
        (session_dir(session_id) / "exec").mkdir(parents=True, exist_ok=True)
        (session_dir(session_id) / "run").mkdir(parents=True, exist_ok=True)
        session_tasks_dir(session_id).mkdir(parents=True, exist_ok=True)
        session_msg_output_dir(session_id).mkdir(parents=True, exist_ok=True)
        session_task_output_dir(session_id).mkdir(parents=True, exist_ok=True)

        if research and not has_identity:
            config = _read_config()
            docs_root = config.get("docs_root") or config.get("research_root")
            if docs_root:
                project_file = Path(docs_root) / "projects" / f"{research}.md"
                if not project_file.exists():
                    project_file.parent.mkdir(parents=True, exist_ok=True)
                    project_file.write_text(
                        f"# {research}\n\n## Overview\n\n### Structure\n\n"
                        f"### Environment\n"
                    )

        _old_docs = Path(__file__).resolve().parents[2] / "docs"
        _new_docs = SESSION_DIR / "docs"
        if _old_docs.exists() and any(_old_docs.iterdir()):
            _new_docs.mkdir(parents=True, exist_ok=True)
            shutil.copytree(str(_old_docs), str(_new_docs), dirs_exist_ok=True)
            shutil.rmtree(str(_old_docs))
            print(f"  [owrap] Migrated {_old_docs} -> {_new_docs}")

        plan_path = get_plan_path(session_id)
        todo_path = None if has_identity else _todo_path_or_none(research)
        input_path = session_input(session_id)

        self.manager.session_id = session_id
        self.manager.research = _parse(_sf(session_id)).get("research", "")
        self.manager.create_context()
        self.manager._housekeeping()
        self.manager.refresh_context_plan(plan_path)
        # Auto-populate Focus from research project file on first create
        cp2 = context_path(session_id)
        if cp2.exists() and research:
            _ct = cp2.read_text()
            if "## Focus\n\n## " in _ct:
                _proj = get_project_file_path(research)
                if _proj.exists():
                    _proj_text = _proj.read_text()
                    _m = re.search(r"current_phase:\s*(\d+)", _proj_text)
                    if _m:
                        _focus = f"Phase {_m.group(1)}"
                        _ct = _ct.replace(
                            "## Focus\n\n## ",
                            f"## Focus\n{_focus}\n\n## ", 1,
                        )
                        cp2.write_text(_ct)
        self.manager.start_watchdog()

        if self.logger:
            self.logger.info(
                "start session=%s research=%s", session_id, research or "none",
            )
        cp = context_path(session_id)
        from ..utils.session.resolver import _parse as _sp
        area_val = area or _sp(_sf(session_id)).get("area")
        memory_path, project_path = resolve_memory_project_paths(research)
        print_orientation(
            session_id, research, plan_path=plan_path, todo_path=todo_path,
            input_path=input_path, context_path=cp, area=area_val,
            memory_path=memory_path, project_path=project_path,
            runner_enabled=_read_config().get("owrap_runner_enabled", True),
            target=_orientation_target(session_id),
        )
        print(f"\n__OWRAP_EXPORT__ SESSION_ID={session_id}")
        if area_val:
            print(f"__OWRAP_EXPORT__ OWRAP_AREA={area_val}")
        sys.exit(0)


class RefreshRunner(BaseRunner):
    """
    Refresh an existing owrap session's context and re-print orientation.
    """

    def run(self, shell_pid=None, session_file=None, research=None,
            session_id=None, area=None):
        """
        Execute the refresh workflow: validate session, update context, and exit.
        """
        if session_id is not None:
            session_path = SESSIONS_DIR / f"{session_id}.session"
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
                        f"  {s['session_id']}  research={s.get('research','-')}  "
                        f"started={s.get('started','-')}  ccsid={_cc}",
                    )
                print()
                print("Either: export SESSION_ID=<id>  OR  "
                      "~/bin/owrap attach <id>  OR  ~/bin/owrap start <name>")
                sys.exit(2)

        data = _parse(session_path)
        existing_research = data.get("research")
        existing_area = data.get("area")
        if research is None:
            research = existing_research
        if (research is None and not data.get("target_kind")
                and data.get("session_mode") != "temp"):
            research = _read_config().get("default_research")

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
                    shell_pid=shell_pid, research=research,
                )
                return

        if research is not None and research != existing_research:
            update_session_field(session_id, "research", research)
        if area is not None:
            update_session_field(session_id, "area", area)
        area_val = area if area is not None else existing_area

        self.manager._housekeeping()

        plan_path = get_plan_path(session_id)
        todo_path = (
            None if data.get("target_kind")
            else _todo_path_or_none(research)
        )
        input_path = session_input(session_id)

        if self.logger:
            self.logger.info(
                "refresh session=%s research=%s", session_id, research or "none",
            )
        cp = context_path(session_id)
        memory_path, project_path = resolve_memory_project_paths(research)
        print_orientation(
            session_id, research, plan_path=plan_path, todo_path=todo_path,
            input_path=input_path, context_path=cp, area=area_val,
            memory_path=memory_path, project_path=project_path,
            runner_enabled=_read_config().get("owrap_runner_enabled", True),
            target=_orientation_target(session_id),
        )
        update_session_field(
            session_id, "last_refresh", time.strftime("%Y-%m-%dT%H:%M:%S"),
        )
        print(f"\n__OWRAP_EXPORT__ SESSION_ID={session_id}")
        if area_val:
            print(f"__OWRAP_EXPORT__ OWRAP_AREA={area_val}")
        sys.exit(0)


class AttachRunner(BaseRunner):
    """
    Attach to an existing owrap session by ID and print orientation.
    """

    def run(self, target_session_id=None):
        """
        Attach to the given session id, research name, or area name, and
        re-export its environment variables.
        """
        if not target_session_id:
            print("ERROR: owrap attach <session_id|research|area> — missing target.")
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
        research = data.get("research", "")
        area = data.get("area", "")
        url = data.get("server_url", "")

        plan_path = get_plan_path(sid)
        todo_path = (
            None if data.get("target_kind")
            else _todo_path_or_none(research)
        )
        input_path = session_input(sid)
        cp = context_path(sid)
        memory_path, project_path = resolve_memory_project_paths(research)

        self.manager.session_id = sid
        print(
            f"ATTACHED session={sid}  research={research or '-'}  "
            f"area={area or '-'}  prev_session_for_this_window={prev or '-'}",
        )
        print_orientation(
            sid, research, url, plan_path, todo_path, input_path,
            context_path=cp, area=area, memory_path=memory_path,
            project_path=project_path, attach=True,
            runner_enabled=_read_config().get("owrap_runner_enabled", True),
            target=_orientation_target(sid),
        )
        print(f"\n__OWRAP_EXPORT__ SESSION_ID={sid}")
        if area:
            print(f"__OWRAP_EXPORT__ OWRAP_AREA={area}")
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
        sid = detach()
        if not sid:
            print("Not attached to any session")
            sys.exit(1)

        remaining = len(attached_ccsids(sid))
        print(f"DETACHED session={sid}  still_attached={remaining}")
        sys.exit(0)


class RestartRunner(BaseRunner):
    """
    Stop and immediately re-start an owrap session.
    """

    def run(self, shell_pid=None, session_file=None, research=None,
            force=False, session_id=None):
        """
        Stop the current session and start a fresh one with the same parameters.
        """
        if self.logger:
            self.logger.info(
                "restart initiated research=%s force=%s session_id=%s",
                research or "none", force, session_id or "none",
            )
        StopRunner(self.manager, self.logger).run(
            no_exit=True, force=force, target=session_id,
        )
        StartRunner(
            self.manager, self.logger, allow_all=self.allow_all,
        ).run(
            shell_pid=shell_pid, session_file=session_file,
            research=research, session_id=session_id,
        )


class UpdateAreaRunner(BaseRunner):
    """
    Update the area (and optionally research) of the current session.
    """

    def run(self, research=None, area=None, child=None):
        """
        Update session fields and re-print orientation with the new area.
        """
        session_id, _, _ = resolve(mode="refresh")
        current = _parse(_sf(session_id))
        if current.get("target_kind") and child:
            print("ERROR: --child applies only to legacy areas")
            sys.exit(2)
        if current.get("target_kind") == "repository":
            print("ERROR: repository-only sessions have no project area")
            sys.exit(2)
        if current.get("target_kind") == "project":
            project_id = research or current.get("project_id", "")
            if area is not None:
                subproject_id = "" if area == "main" else area
            elif project_id == current.get("project_id", ""):
                subproject_id = current.get("subproject_id", "")
            else:
                subproject_id = ""
            candidate = {
                **current, "project_id": project_id,
                "subproject_id": subproject_id,
            }
            try:
                target = resolve_memory_target(candidate)
            except (OSError, ValueError) as exc:
                print(f"ERROR: {exc}")
                sys.exit(2)
            update_session_field(session_id, "project_id", project_id)
            update_session_field(session_id, "subproject_id", subproject_id)
            update_session_field(
                session_id, "repositories",
                json.dumps(list(target.repository_ids), separators=(",", ":")),
            )
            for field in ("branch_parent", "branch_repository", "branch_ref"):
                update_session_field(session_id, field, getattr(target, field))
            research = current.get("research", "")
            area = current.get("area", "")
            child = current.get("child", "")
        if research:
            update_session_field(session_id, "research", research)
        if area:
            update_session_field(session_id, "area", area)
            update_session_field(session_id, "child", child)
        memory_path, project_path = resolve_memory_project_paths(research)
        cp = context_path(session_id)
        plan_path = get_plan_path(session_id)
        input_path = session_input(session_id)
        todo_path = (
            None if current.get("target_kind")
            else _todo_path_or_none(research)
        )
        print_orientation(
            session_id, research, plan_path=plan_path, todo_path=todo_path,
            input_path=input_path, context_path=cp, area=area,
            memory_path=memory_path, project_path=project_path,
            runner_enabled=_read_config().get("owrap_runner_enabled", True),
            target=_orientation_target(session_id),
        )
        print(f"\n__OWRAP_EXPORT__ SESSION_ID={session_id}")
        if area:
            print(f"__OWRAP_EXPORT__ OWRAP_AREA={area}")
        sys.exit(0)


class SpawnRunner(BaseRunner):
    """
    Spawn a child area under the current session's research and area.
    """

    def run(self, child):
        """
        Create a child area as a genuinely isolated new session.
        """
        parent_sid, parent_path, _ = resolve(mode="refresh")
        if not parent_sid:
            print("Error: no active session — run owrap start first",
                  file=sys.stderr)
            sys.exit(1)
        sess = _parse(_sf(parent_sid))
        research = sess.get("research")
        area = sess.get("area")
        if not research or not area:
            print(
                "Error: current session has no research/area set — run "
                "owrap start <research> <area> first", file=sys.stderr,
            )
            sys.exit(1)
        new_area = f"{area}-{child}"
        session_id, session_path = _mint_from(parent_sid, parent_sid)
        update_session_field(session_id, "area", new_area)
        update_session_field(session_id, "child", child)
        memory_path, project_path = resolve_memory_project_paths(research)
        cp = context_path(session_id)
        plan_path = get_plan_path(session_id)
        input_path = session_input(session_id)
        todo_path = _todo_path_or_none(research)
        print(
            f"[owrap] Spawned child area '{new_area}' "
            f"(parent: {area}) under research '{research}'.",
        )
        print_orientation(
            session_id, research, plan_path=plan_path, todo_path=todo_path,
            input_path=input_path, context_path=cp, area=new_area,
            memory_path=memory_path, project_path=project_path,
            runner_enabled=_read_config().get("owrap_runner_enabled", True),
        )
        print(f"\n__OWRAP_EXPORT__ SESSION_ID={session_id}")
        print(f"__OWRAP_EXPORT__ OWRAP_AREA={new_area}")
        sys.exit(0)


def main():
    parser = argparse.ArgumentParser(description="Start an owrap session")
    parser.add_argument("research", nargs="?", default=None, help="Research project name")
    parser.add_argument("--shell-pid", type=int, default=None, help="Shell PID")
    parser.add_argument(
        "--session-file", type=str, default=None,
        help="Session file path",
    )
    args = parser.parse_args()

    from ..manager import Manager
    manager = Manager()
    StartRunner(manager).run(
        shell_pid=args.shell_pid, session_file=args.session_file,
        research=args.research,
    )


if __name__ == "__main__":
    main()
