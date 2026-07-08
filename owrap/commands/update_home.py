import json
import os
import shutil
import subprocess
import sys
import tarfile
from datetime import datetime
from pathlib import Path

from ..base import BaseRunner
from ..utils.paths import OWRAP_HOME, OWRAP_HOME_POINTER_FILE, CONFIGS_DIR, KEEPALIVE_PID_FILE, _read_config


class UpdateHomeRunner(BaseRunner):
    """Point OWRAP_HOME at a new path.

    Default: lightweight repoint — just updates the pointer file. Use this when the
    target already has valid content (e.g. a synced mount from another machine) or is
    a fresh path you'll populate via normal `owrap` usage afterward.

    With --migrate: backup, stop live processes, atomically move existing content,
    update the pointer file, and re-sync the current workspace. Use this to actually
    relocate existing data on the same machine.
    """

    def run(self, new_path: str, dry_run: bool = False, migrate: bool = False):
        current_home = OWRAP_HOME
        target = Path(new_path).expanduser().resolve()
        if migrate:
            self._run_migrate(current_home, target, dry_run)
        else:
            self._run_repoint(current_home, target, dry_run)

    # ---- lightweight repoint (default) ----

    def _validate_repoint(self, current_home: Path, target: Path) -> str | None:
        if target == current_home:
            return "target path is the same as the current OWRAP_HOME"
        if target.exists() and target.is_file():
            return f"target path {target} exists and is a regular file, not a directory"
        parent = target.parent
        while not parent.exists():
            parent = parent.parent
        if not os.access(parent, os.W_OK):
            return f"target parent directory {parent} is not writable"
        return None

    def _run_repoint(self, current_home: Path, target: Path, dry_run: bool):
        error = self._validate_repoint(current_home, target)
        if error:
            print(f"Error: {error}")
            sys.exit(1)

        if dry_run:
            print("[dry-run] Would repoint OWRAP_HOME:")
            print(f"  from: {current_home}")
            print(f"  to:   {target}")
            print(f"  would update pointer file: {OWRAP_HOME_POINTER_FILE}")
            print("  no backup, no process changes, no data move (use --migrate to relocate existing content)")
            print("  you would then run `owrap sync` to re-apply templates for the current workspace")
            return

        OWRAP_HOME_POINTER_FILE.write_text(str(target) + "\n")
        print(f"Pointer file updated: {OWRAP_HOME_POINTER_FILE} -> {target}")
        print(f"OWRAP_HOME now points to: {target}")
        print("Run `owrap sync` to re-apply templates for the current workspace.")
        print("Note: any shell with OWRAP_HOME already exported will keep overriding the pointer file until updated/unset there.")

    # ---- full migration (--migrate) ----

    def _run_migrate(self, current_home: Path, target: Path, dry_run: bool):
        workspaces = self._list_workspaces()

        error = self._validate(current_home, target)
        if error:
            print(f"Error: {error}")
            sys.exit(1)

        if dry_run:
            self._print_dry_run(current_home, target, workspaces, self._current_workspace_name())
            return

        backup_path = self._backup(current_home)
        print(f"Backup created: {backup_path}")

        print("Stopping server pool and running tasks...")
        from ..session.stop import KillServersRunner
        KillServersRunner().run()
        self._stop_keepalive()

        try:
            self._move(current_home, target)
        except Exception as e:
            print(f"Error during move: {e}")
            print(f"Original directory should still be intact at {current_home}; backup also available at {backup_path}.")
            sys.exit(1)

        OWRAP_HOME_POINTER_FILE.write_text(str(target) + "\n")
        print(f"Pointer file updated: {OWRAP_HOME_POINTER_FILE} -> {target}")

        owrap_root = Path(__file__).resolve().parents[2]
        current_ws_name = self._current_workspace_name()
        current_ws_ok = self._resync_current_workspace(owrap_root)
        other_workspaces = [w for w in workspaces if w != current_ws_name]

        print(f"\nOWRAP_HOME moved: {current_home} -> {target}")
        print(f"Backup: {backup_path}")
        if current_ws_ok:
            print("Current session's workspace re-synced automatically.")
        else:
            print("Automatic re-sync of the current session's workspace FAILED — run `owrap sync` manually.")
        if other_workspaces:
            print(f"Other configured workspaces found (re-sync these manually from a session bound to each): {', '.join(other_workspaces)}")
        print("Note: any shell with OWRAP_HOME already exported will keep overriding the pointer file until updated/unset there.")

    def _list_workspaces(self) -> list[str]:
        if not CONFIGS_DIR.exists():
            return []
        names = []
        for f in CONFIGS_DIR.glob("*.json"):
            if f.name == "base.json" or f.name.endswith("_permit.json"):
                continue
            names.append(f.stem)
        return names

    def _current_workspace_name(self) -> str:
        try:
            return _read_config().get("default_workspace", "")
        except Exception:
            return ""

    def _validate(self, current_home: Path, target: Path) -> str | None:
        if not current_home.exists():
            return f"current OWRAP_HOME {current_home} does not exist"
        if target == current_home:
            return "target path is the same as the current OWRAP_HOME"
        try:
            target.relative_to(current_home)
            return f"target path {target} is nested inside current OWRAP_HOME ({current_home})"
        except ValueError:
            pass
        if target.exists():
            if any(target.iterdir()):
                return f"target path {target} already exists and is not empty"
            if not os.access(target, os.W_OK):
                return f"target path {target} exists but is not writable (check ownership/permissions)"
        parent = target.parent
        while not parent.exists():
            parent = parent.parent
        if not os.access(parent, os.W_OK):
            return f"target parent directory {parent} is not writable"
        return None

    def _print_dry_run(self, current_home: Path, target: Path, workspaces: list[str], current_ws_name: str):
        print("[dry-run] Would move OWRAP_HOME:")
        print(f"  from: {current_home}")
        print(f"  to:   {target}")
        try:
            files = [f for f in current_home.rglob("*") if f.is_file()]
            total_size = sum(f.stat().st_size for f in files)
            print(f"  contents: {len(files)} files, {total_size / (1024*1024):.1f} MB")
        except Exception:
            pass
        print("  would stop: server pool + running tasks, keepalive daemon (if running)")
        print("  would create a backup archive before moving")
        print(f"  would update pointer file: {OWRAP_HOME_POINTER_FILE}")
        other_workspaces = [w for w in workspaces if w != current_ws_name]
        print("  would auto re-sync the current session's workspace")
        if other_workspaces:
            print(f"  other configured workspaces to re-sync manually: {', '.join(other_workspaces)}")

    def _backup(self, current_home: Path) -> Path:
        backup_dir = Path.home() / ".owrap_backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = backup_dir / f"owrap_home_backup_{timestamp}.tar.gz"
        with tarfile.open(backup_path, "w:gz") as tar:
            tar.add(str(current_home), arcname=current_home.name)
        return backup_path

    def _stop_keepalive(self):
        from ..session.stop import _pid_alive, _kill_pid, _wait_dead
        if KEEPALIVE_PID_FILE.exists():
            try:
                pid = int(KEEPALIVE_PID_FILE.read_text().strip())
                if _pid_alive(pid):
                    _kill_pid(pid)
                    _wait_dead([pid])
            except (ValueError, OSError):
                pass

    def _same_filesystem(self, a: Path, b: Path) -> bool:
        try:
            return os.stat(a).st_dev == os.stat(b if b.exists() else b.parent).st_dev
        except OSError:
            return False

    def _move(self, current_home: Path, target: Path):
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            # _validate() already confirmed it's empty and writable; remove it so
            # shutil.move can't nest src inside it (shutil.move moves INTO an
            # existing directory rather than replacing it).
            target.rmdir()
        if self._same_filesystem(current_home, target.parent):
            os.rename(str(current_home), str(target))
        else:
            shutil.move(str(current_home), str(target))
            if not target.exists() or not any(target.iterdir()):
                raise RuntimeError("move appears incomplete — target is missing or empty after move")

    def _resync_current_workspace(self, owrap_root: Path) -> bool:
        try:
            result = subprocess.run(
                [sys.executable, "-m", "owrap.runner", "sync"],
                cwd=str(owrap_root), capture_output=True, text=True, timeout=30,
            )
        except Exception:
            return False
        print(result.stdout)
        if result.returncode != 0:
            if result.stderr:
                print(result.stderr, file=sys.stderr)
            return False
        task_path = None
        for line in result.stdout.splitlines():
            if line.startswith("sync_task written: "):
                task_path = line.split(": ", 1)[1].strip()
        if not task_path:
            return False
        try:
            fallback_result = subprocess.run(
                [sys.executable, "-m", "owrap.runner", "f", task_path],
                cwd=str(owrap_root), capture_output=True, text=True, timeout=120,
            )
        except Exception:
            return False
        print(fallback_result.stdout)
        if fallback_result.returncode != 0 and fallback_result.stderr:
            print(fallback_result.stderr, file=sys.stderr)
        return fallback_result.returncode == 0
