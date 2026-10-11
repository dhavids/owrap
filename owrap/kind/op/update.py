import os
import shutil
import subprocess
import sys
import tarfile
from datetime import datetime
from pathlib import Path

from . import Op
from ..run.daemon import Daemon
from ...utils.paths import (
    CONFIGS_DIR, OWRAP_HOME, OWRAP_HOME_POINTER_FILE, OWRAP_ROOT, _read_config,
)


class Update(Op):
    """
    Repoint, or (with `migrate`) actually relocate, `OWRAP_HOME`.
    """

    kind = "update"

    usage = {
        "do": {
            "usage": "<new_path> [--dry-run] [--migrate]",
            "args": [
                ("new_path", "new absolute path for OWRAP_HOME"),
                ("migrate", "relocate existing content, not just repoint"),
            ],
            "examples": ["/mnt/new_home", "/mnt/new_home --migrate"],
        },
    }

    messages = {"do": "{message}"}


    # Public Methods

    def do(
        self, new_path: str = None, dry_run: bool = False, migrate: bool = False,
    ) -> None:
        if new_path is None:
            self._usage("do")
        current_home = OWRAP_HOME
        target = Path(new_path).expanduser().resolve()
        if migrate:
            message = self._update_migrate(current_home, target, dry_run)
        else:
            message = self._update_repoint(current_home, target, dry_run)
        self._ok("do", message=message)


    # Private Methods

    def _update_repoint(self, current_home: Path, target: Path, dry_run: bool) -> str:
        error = self._validate_repoint(current_home, target)
        if error:
            self._fail(error)
        if dry_run:
            return (
                "[dry-run] Would repoint OWRAP_HOME:\n"
                f"  from: {current_home}\n  to:   {target}\n"
                f"  would update pointer file: {OWRAP_HOME_POINTER_FILE}\n"
                "  no backup, no process changes, no data move "
                "(use --migrate to relocate existing content)\n"
                "  you would then run `owrap sync` to re-apply "
                "templates for the current workspace"
            )
        OWRAP_HOME_POINTER_FILE.write_text(str(target) + "\n")
        return (
            f"Pointer file updated: {OWRAP_HOME_POINTER_FILE} -> {target}\n"
            f"OWRAP_HOME now points to: {target}\n"
            "Run `owrap sync` to re-apply templates for the current "
            "workspace.\n"
            "Note: any shell with OWRAP_HOME already exported will keep "
            "overriding the pointer file until updated/unset there."
        )

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

    def _update_migrate(self, current_home: Path, target: Path, dry_run: bool) -> str:
        workspaces = self._list_workspaces()
        error = self._validate_migrate(current_home, target)
        if error:
            self._fail(error)
        if dry_run:
            return self._migrate_dry_run_report(
                current_home, target, workspaces, self._current_workspace_name(),
            )

        backup_path = self._backup(current_home)
        print(f"Backup created: {backup_path}")
        print("Stopping server pool and running tasks...")
        Daemon()._on_kill()

        try:
            self._move(current_home, target)
        except Exception as e:
            self._fail(
                f"during move: {e}. Original directory should still be intact "
                f"at {current_home}; backup also available at {backup_path}."
            )

        OWRAP_HOME_POINTER_FILE.write_text(str(target) + "\n")
        current_ws_name = self._current_workspace_name()
        current_ws_ok = self._resync_current_workspace()
        other_workspaces = [w for w in workspaces if w != current_ws_name]

        lines = [
            f"Pointer file updated: {OWRAP_HOME_POINTER_FILE} -> {target}",
            f"OWRAP_HOME moved: {current_home} -> {target}",
            f"Backup: {backup_path}",
        ]
        if current_ws_ok:
            lines.append("Current session's workspace re-synced automatically.")
        else:
            lines.append(
                "Automatic re-sync of the current session's workspace FAILED "
                "— run `owrap sync` manually."
            )
        if other_workspaces:
            lines.append(
                f"Other configured workspaces found (re-sync these manually "
                f"from a session bound to each): {', '.join(other_workspaces)}"
            )
        lines.append(
            "Note: any shell with OWRAP_HOME already exported will keep "
            "overriding the pointer file until updated/unset there."
        )
        return "\n".join(lines)

    def _list_workspaces(self) -> list:
        if not CONFIGS_DIR.exists():
            return []
        return [
            f.stem for f in CONFIGS_DIR.glob("*.json")
            if f.name != "base.json" and not f.name.endswith("_permit.json")
        ]

    def _current_workspace_name(self) -> str:
        try:
            return _read_config().get("default_workspace", "")
        except Exception:
            return ""

    def _validate_migrate(self, current_home: Path, target: Path) -> str | None:
        if not current_home.exists():
            return f"current OWRAP_HOME {current_home} does not exist"
        if target == current_home:
            return "target path is the same as the current OWRAP_HOME"
        try:
            target.relative_to(current_home)
            return (
                f"target path {target} is nested inside current OWRAP_HOME "
                f"({current_home})"
            )
        except ValueError:
            pass
        if target.exists():
            if any(target.iterdir()):
                return f"target path {target} already exists and is not empty"
            if not os.access(target, os.W_OK):
                return (
                    f"target path {target} exists but is not writable "
                    f"(check ownership/permissions)"
                )
        parent = target.parent
        while not parent.exists():
            parent = parent.parent
        if not os.access(parent, os.W_OK):
            return f"target parent directory {parent} is not writable"
        return None

    def _migrate_dry_run_report(
        self, current_home: Path, target: Path, workspaces: list, current_ws_name: str,
    ) -> str:
        lines = [
            "[dry-run] Would move OWRAP_HOME:",
            f"  from: {current_home}", f"  to:   {target}",
        ]
        try:
            files = [f for f in current_home.rglob("*") if f.is_file()]
            total_size = sum(f.stat().st_size for f in files)
            lines.append(
                f"  contents: {len(files)} files, {total_size / (1024*1024):.1f} MB",
            )
        except Exception:
            pass
        lines.append("  would stop: server pool + running tasks, daemon (if running)")
        lines.append("  would create a backup archive before moving")
        lines.append(f"  would update pointer file: {OWRAP_HOME_POINTER_FILE}")
        lines.append("  would auto re-sync the current session's workspace")
        other_workspaces = [w for w in workspaces if w != current_ws_name]
        if other_workspaces:
            lines.append(
                f"  other configured workspaces to re-sync manually: "
                f"{', '.join(other_workspaces)}"
            )
        return "\n".join(lines)

    def _backup(self, current_home: Path) -> Path:
        backup_dir = Path.home() / ".owrap_backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = backup_dir / f"owrap_home_backup_{timestamp}.tar.gz"
        with tarfile.open(backup_path, "w:gz") as tar:
            tar.add(str(current_home), arcname=current_home.name)
        return backup_path

    def _same_filesystem(self, a: Path, b: Path) -> bool:
        try:
            return os.stat(a).st_dev == os.stat(b if b.exists() else b.parent).st_dev
        except OSError:
            return False

    def _move(self, current_home: Path, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            target.rmdir()
        if self._same_filesystem(current_home, target.parent):
            os.rename(str(current_home), str(target))
        else:
            shutil.move(str(current_home), str(target))
            if not target.exists() or not any(target.iterdir()):
                raise RuntimeError(
                    "move appears incomplete — target is missing or empty after move"
                )

    def _resync_current_workspace(self) -> bool:
        """
        Re-sync the current workspace in a fresh subprocess, against
        the new CLI (`owrap.cli`), not the old `owrap.runner`.
        """
        try:
            result = subprocess.run(
                [sys.executable, "-m", "owrap.cli", "sync"],
                cwd=str(OWRAP_ROOT), capture_output=True, text=True, timeout=30,
            )
        except Exception:
            return False
        print(result.stdout)
        if result.returncode != 0:
            if result.stderr:
                print(result.stderr, file=sys.stderr)
            return False
        return True
