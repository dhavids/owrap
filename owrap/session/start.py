import argparse
import json
import os
import secrets
import sys
from pathlib import Path

from ..base import BaseRunner
from ..manager import Manager
from ..utils.paths import SESSION_DIR, TASKS_DIR, RUN_OUTPUT_DIR, EXEC_OUTPUT_DIR, READ_OUTPUT_DIR
from ..utils.paths import get_plan_path, get_self_path, get_todo_path, session_input, _read_config, SERVERS_DIR, STATE_FILE
from .orientation import print_orientation


def _prune_logs(max_logs: int):
    owrap_dir = Path.home() / ".owrap"
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
    def run(self, shell_pid=None, session_file=None, research=None):
        if research is None:
            research = _read_config().get("default_research")
        session_id = secrets.token_hex(3)
        _, url = Manager.get_or_start_server()

        session_path = Path(session_file) if session_file else SESSION_DIR / "session"
        session_path.parent.mkdir(parents=True, exist_ok=True)
        config = _read_config()
        max_logs = int(config.get("max_servers", 1)) * 2
        _prune_logs(max_logs)
        lines = [f"session_id={session_id}", f"server_url={url}"]
        if research:
            lines.append(f"research={research}")
        with open(session_path, "w") as f:
            f.write("\n".join(lines) + "\n")

        TASKS_DIR.mkdir(parents=True, exist_ok=True)
        RUN_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        EXEC_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        READ_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

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

        plan_path = get_plan_path(session_id)
        todo_path = get_todo_path(research)
        self_path = get_self_path()
        input_path = session_input(session_id)

        if self.logger:
            self.logger.info("start session=%s research=%s url=%s", session_id, research or "none", url)
        print_orientation(session_id, research, url, plan_path, todo_path, self_path, input_path)
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
