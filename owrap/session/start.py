import argparse
import json
import os
import sys
import time
from pathlib import Path

from ..base import BaseRunner
from ..manager import Manager
from ..utils.paths import SESSION_DIR, EXEC_OUTPUT_DIR, READ_OUTPUT_DIR
from ..utils.paths import get_plan_path, get_todo_path, session_input, _read_config, SERVERS_DIR, STATE_FILE, context_path, get_workspace_config, BASE_CONFIG_FILE
from ..utils.paths import session_dir, session_tasks_dir, session_msg_output_dir, session_task_output_dir, session_precompact_dir
from ..utils.session_resolver import resolve, update_session_field, migrate_legacy_files, session_file as _sf, ccsid_pointer, _write as _sr_write, SESSIONS_DIR, BY_CCSID_DIR, list_sessions, _parse, attach
from .orientation import print_orientation
from .stop import StopRunner


def _prune_logs(max_logs: int):
    owrap_dir = SESSION_DIR
    try:
        running_pids = set()
        if SERVERS_DIR.exists():
            for f in SERVERS_DIR.glob("*.json"):
                try:
                    data = json.loads(f.read_text())
                    pid = data.get("pid")
                    if pid:
                        running_pids.add(pid)
                except Exception:
                    pass
        try:
            with open(STATE_FILE) as f:
                data = json.load(f)
                pid = data.get("pid")
                if pid:
                    running_pids.add(pid)
        except Exception:
            pass
        log_files = sorted(
            [f for f in owrap_dir.glob("owrap_*.log") if not f.name.startswith("owrap_start_")],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        kept = 0
        for f in log_files:
            try:
                pid = int(f.stem.replace("owrap_", ""))
            except ValueError:
                continue
            if pid in running_pids or kept < max_logs:
                kept += 1
            else:
                f.unlink(missing_ok=True)
        for f in owrap_dir.glob("owrap_start_*.log"):
            f.unlink(missing_ok=True)
    except Exception:
        pass


class StartRunner(BaseRunner):
    def run(self, shell_pid=None, session_file=None, research=None, session_id=None, area=None):
        if research is None:
            research = _read_config().get("default_research")
        migrate_legacy_files()
        
        if session_id is not None:
            sf_path = _sf(session_id)
            if sf_path.exists():
                session_path = sf_path
            else:
                ccsid = os.environ.get("CLAUDE_CODE_SESSION_ID", "").strip()
                _sr_write(sf_path, {"session_id": session_id, "claude_session_id": ccsid, "started": time.strftime("%Y-%m-%dT%H:%M:%S")})
                if ccsid:
                    BY_CCSID_DIR.mkdir(parents=True, exist_ok=True)
                    ccsid_pointer(ccsid).write_text(session_id)
                session_path = sf_path
        else:
            session_id, session_path, source = resolve(mode="start")

        from ..utils.pool import _pool_active, ensure_min_servers, _ensure_keepalive
        if _pool_active():
            ensure_min_servers()
            _ensure_keepalive()
        else:
            Manager().ensure_running()

        if research:
            update_session_field(session_id, "research", research)
        if area:
            update_session_field(session_id, "area", area)

        # Resolve workspace name: explicit research → use as workspace key, else default_workspace
        base = _read_config()
        workspace_name = research or base.get("default_workspace", "")
        _pc_check = get_workspace_config(workspace_name) if workspace_name else {}
        if not _pc_check and workspace_name != base.get("default_workspace", ""):
            workspace_name = base.get("default_workspace", workspace_name)
        if workspace_name:
            update_session_field(session_id, "workspace", workspace_name)

        config = _read_config()
        max_logs = int(config.get("max_servers", 1)) * 2
        _prune_logs(max_logs)

        EXEC_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        READ_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        session_dir(session_id).mkdir(parents=True, exist_ok=True)
        (session_dir(session_id) / "exec").mkdir(parents=True, exist_ok=True)
        (session_dir(session_id) / "run").mkdir(parents=True, exist_ok=True)
        session_tasks_dir(session_id).mkdir(parents=True, exist_ok=True)
        session_msg_output_dir(session_id).mkdir(parents=True, exist_ok=True)
        session_task_output_dir(session_id).mkdir(parents=True, exist_ok=True)
        session_precompact_dir(session_id).mkdir(parents=True, exist_ok=True)

        if research:
            config = _read_config()
            research_root = config.get("research_root")
            if research_root:
                project_file = Path(research_root) / "projects" / f"{research}.md"
                if not project_file.exists():
                    project_file.parent.mkdir(parents=True, exist_ok=True)
                    project_file.write_text(
                        f"---\nname: {research}\nactive_plan: none\n---\n\n## TODO\n\n## DONE\n"
                    )

        _old_docs = Path(__file__).resolve().parents[2] / "docs"
        _new_docs = SESSION_DIR / "docs"
        if _old_docs.exists() and any(_old_docs.iterdir()):
            import shutil
            _new_docs.mkdir(parents=True, exist_ok=True)
            shutil.copytree(str(_old_docs), str(_new_docs), dirs_exist_ok=True)
            shutil.rmtree(str(_old_docs))
            print(f"  [owrap] Migrated {_old_docs} -> {_new_docs}")

        plan_path = get_plan_path(session_id)
        todo_path = get_todo_path(research)
        input_path = session_input(session_id)

        self.manager.session_id = session_id
        self.manager.create_context()
        self.manager._housekeeping()
        self.manager.refresh_context_plan(plan_path)
        # Auto-populate Focus from research project file on first create
        import re as _re
        cp2 = context_path(session_id)
        if cp2.exists() and research:
            _ct = cp2.read_text()
            if "## Focus\n\n## " in _ct:
                _proj = get_todo_path(research)
                if _proj.exists():
                    _proj_text = _proj.read_text()
                    _m = _re.search(r"current_phase:\s*(\d+)", _proj_text)
                    if _m:
                        _focus = f"Phase {_m.group(1)}"
                        _ct = _ct.replace("## Focus\n\n## ", f"## Focus\n{_focus}\n\n## ", 1)
                        cp2.write_text(_ct)
        self.manager.start_watchdog()

        if self.logger:
            self.logger.info("start session=%s research=%s", session_id, research or "none")
        cp = context_path(session_id)
        from ..utils.session_resolver import _parse as _sp
        area_val = area or _sp(_sf(session_id)).get("area")
        memory_path = project_path = None
        if research:
            _rr = _read_config().get("research_root")
            if _rr:
                _mp = Path(_rr) / "memory" / f"{research}.md"
                _pp = Path(_rr) / "projects" / f"{research}.md"
                memory_path = _mp if _mp.exists() else None
                project_path = _pp if _pp.exists() else None
        print_orientation(session_id, research, plan_path=plan_path, todo_path=todo_path, input_path=input_path, context_path=cp,
                          area=area_val, memory_path=memory_path, project_path=project_path)
        print(f"\n__OWRAP_EXPORT__ SESSION_ID={session_id}")
        if area_val:
            print(f"__OWRAP_EXPORT__ OWRAP_AREA={area_val}")
        sys.exit(0)


class RefreshRunner(BaseRunner):
    def run(self, shell_pid=None, session_file=None, research=None, session_id=None, area=None):
        if session_id is not None:
            session_path = SESSION_DIR / "sessions" / f"{session_id}.session"
            if not session_path.exists():
                print(f"ERROR: session '{session_id}' not found. Use 'owrap stat' to list sessions.")
                sys.exit(2)
        else:
            session_id, session_path, source = resolve(mode="refresh")
            if session_id is None:
                print("ERROR: cannot refresh — no SESSION_ID in env and no Claude session anchor matched.")
                print()
                print("Known sessions:")
                for s in list_sessions():
                    ccsid_val = s.get("claude_session_id", "-")
                    print(f"  {s['session_id']}  research={s.get('research','-')}  started={s.get('started','-')}  ccsid={ccsid_val[:8] if ccsid_val != '-' else '-'}")
                print()
                print("Either: export SESSION_ID=<id>  OR  ~/bin/owrap attach <id>  OR  ~/bin/owrap start <name>")
                sys.exit(2)

        data = _parse(session_path)
        existing_research = data.get("research")
        existing_area = data.get("area")
        workspace_name = data.get("workspace") or _read_config().get("default_workspace", "")
        if research is None:
            research = existing_research
        if research is None:
            research = _read_config().get("default_research")

        from ..utils.pool import _pool_active, ensure_min_servers, _ensure_keepalive
        if _pool_active():
            ensure_min_servers()
            _ensure_keepalive()
        else:
            url = self.manager.ensure_running()
            if url is None:
                os.environ["SESSION_ID"] = session_id
                StartRunner(self.manager).run(shell_pid=shell_pid, research=research)
                return

        if research != existing_research:
            update_session_field(session_id, "research", research)
        if area is not None:
            update_session_field(session_id, "area", area)
        area_val = area if area is not None else existing_area

        self.manager._housekeeping()

        plan_path = get_plan_path(session_id)
        todo_path = get_todo_path(research)
        input_path = session_input(session_id)

        if self.logger:
            self.logger.info("refresh session=%s research=%s", session_id, research or "none")
        cp = context_path(session_id)
        memory_path = project_path = None
        if research:
            _rr = _read_config().get("research_root")
            if _rr:
                _mp = Path(_rr) / "memory" / f"{research}.md"
                _pp = Path(_rr) / "projects" / f"{research}.md"
                memory_path = _mp if _mp.exists() else None
                project_path = _pp if _pp.exists() else None
        print_orientation(session_id, research, plan_path=plan_path, todo_path=todo_path, input_path=input_path, context_path=cp,
                          area=area_val, memory_path=memory_path, project_path=project_path)
        update_session_field(session_id, "last_refresh", time.strftime("%Y-%m-%dT%H:%M:%S"))
        print(f"\n__OWRAP_EXPORT__ SESSION_ID={session_id}")
        if area_val:
            print(f"__OWRAP_EXPORT__ OWRAP_AREA={area_val}")
        sys.exit(0)


class AttachRunner(BaseRunner):
    def run(self, target_session_id=None):
        if not target_session_id:
            print("ERROR: owrap attach <session_id> — missing session_id.")
            print()
            print("Known sessions:")
            for s in list_sessions():
                ccsid_val = s.get("claude_session_id", "-")
                print(f"  {s['session_id']}  research={s.get('research','-')}  started={s.get('started','-')}  ccsid={ccsid_val[:8] if ccsid_val != '-' else '-'}")
            sys.exit(2)
        try:
            sid, sf, prev = attach(target_session_id)
        except (FileNotFoundError, RuntimeError) as e:
            print(f"ERROR: {e}")
            sys.exit(2)

        data = _parse(sf)
        research = data.get("research", "")
        url = data.get("server_url", "")

        plan_path = get_plan_path(sid)
        todo_path = get_todo_path(research)
        input_path = session_input(sid)
        cp = context_path(sid)

        self.manager.session_id = sid
        print(f"ATTACHED session={sid}  research={research or '-'}  prev_session_for_this_window={prev or '-'}")
        print_orientation(sid, research, url, plan_path, todo_path, input_path, context_path=cp, attach=True)
        print(f"\n__OWRAP_EXPORT__ SESSION_ID={sid}")
        sys.exit(0)


class RestartRunner(BaseRunner):
    def run(self, shell_pid=None, session_file=None, research=None, force=False, session_id=None):
        if self.logger:
            self.logger.info("restart initiated research=%s force=%s session_id=%s", research or "none", force, session_id or "none")
        StopRunner(self.manager, self.logger).run(no_exit=True, force=force, target=session_id)
        StartRunner(self.manager, self.logger, allow_all=self.allow_all).run(
            shell_pid=shell_pid, session_file=session_file, research=research, session_id=session_id)


class UpdateAreaRunner(BaseRunner):
    def run(self, research=None, area=None):
        session_id, _, _ = resolve(mode="refresh")
        if research:
            update_session_field(session_id, "research", research)
        if area:
            update_session_field(session_id, "area", area)
        _rr = _read_config().get("research_root")
        memory_path = project_path = None
        if research and _rr:
            _mp = Path(_rr) / "memory" / f"{research}.md"
            _pp = Path(_rr) / "projects" / f"{research}.md"
            memory_path = _mp if _mp.exists() else None
            project_path = _pp if _pp.exists() else None
        cp = context_path(session_id)
        plan_path = get_plan_path(session_id)
        input_path = session_input(session_id)
        todo_path = get_todo_path(research)
        print_orientation(session_id, research, plan_path=plan_path, todo_path=todo_path,
                          input_path=input_path, context_path=cp,
                          area=area, memory_path=memory_path,
                          project_path=project_path)
        print(f"\n__OWRAP_EXPORT__ SESSION_ID={session_id}")
        if area:
            print(f"__OWRAP_EXPORT__ OWRAP_AREA={area}")
        sys.exit(0)


def main():
    parser = argparse.ArgumentParser(description="Start an owrap session")
    parser.add_argument("research", nargs="?", default=None, help="Research project name")
    parser.add_argument("--shell-pid", type=int, default=None, help="Shell PID")
    parser.add_argument("--session-file", type=str, default=None, help="Session file path")
    args = parser.parse_args()

    from ..manager import Manager
    manager = Manager()
    StartRunner(manager).run(
        shell_pid=args.shell_pid, session_file=args.session_file, research=args.research)


if __name__ == "__main__":
    main()
