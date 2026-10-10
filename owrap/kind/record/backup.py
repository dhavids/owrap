import os
import shutil
import time
from pathlib import Path

from . import Record
from ...session.resolver import _parse, resolve_session_or_exit, session_file
from ...utils.match import require_unique_match
from ...utils.memory.records import resolve_memory_target
from ...utils.paths import BACKUPS_DIR


class Backup(Record):
    """
    Snapshot and restore a project/subproject/repository's own
    Markdown records, kept under `OWRAP_HOME`, never alongside the
    records themselves. `add` creates a timestamped snapshot, `get`
    lists available snapshots, `restore` applies one back over the
    live files, `remove` deletes one or all.
    """

    kind = "backup"

    usage = {
        "add": {
            "usage": "[<target>]",
            "args": [("target", "session id/project/subproject/repository; "
                                 "defaults to the attached session")],
            "examples": ["", "myproject"],
        },
        "get": {
            "usage": "[<target>] [<timestamp>]",
            "args": [("timestamp", "omit to list available snapshots")],
            "examples": ["", "myproject", "myproject 20260101T120000"],
        },
        "restore": {
            "usage": "[<target>] <timestamp>",
            "args": [("timestamp", "'latest' or an unambiguous prefix")],
            "examples": ["myproject latest"],
        },
        "remove": {
            "usage": "[<target>] [<which>]",
            "args": [("which", "'latest' (default), 'all', or a timestamp prefix")],
            "examples": ["myproject", "myproject all", "myproject 20260101"],
        },
    }

    messages = {
        "add": "{message}",
        "get": "{message}",
        "restore": "{message}",
        "remove": "{message}",
    }


    # Public Methods

    def add(self, target: str = None) -> None:
        """
        Copy every record file `target` covers into a new timestamped
        snapshot directory.
        """
        memory_target = self._resolve_backup_target(target)
        label = self._backup_label(memory_target)
        sources = self._backup_sources(memory_target)
        existing = {name: p for name, p in sources.items() if p.exists()}
        if not existing:
            self._fail(f"no record files found for '{label}' — nothing to back up.")

        timestamp = time.strftime("%Y%m%dT%H%M%S")
        dest_dir = self._backup_dir(memory_target) / timestamp
        dest_dir.mkdir(parents=True, exist_ok=True)
        for name, src in existing.items():
            shutil.copy2(src, dest_dir / name)
        self._ok(
            "add",
            message=f"BACKUP {label} -> {dest_dir} ({', '.join(sorted(existing))})",
        )

    def get(self, target: str = None, timestamp: str = None) -> None:
        """
        List `target`'s available snapshots, newest first.
        """
        memory_target = self._resolve_backup_target(target)
        label = self._backup_label(memory_target)
        available = self._available_backups(memory_target)
        if not available:
            self._fail(f"no backups found for '{label}'.")
        lines = [f"Available backups for '{label}' (newest first):"]
        lines.extend(f"  {ts}" for ts in available)
        lines.append(
            f"Run `owrap backup restore {target or label} <timestamp>` or "
            f"`owrap backup restore {target or label} latest` to restore one."
        )
        self._ok("get", message="\n".join(lines))

    def restore(self, target: str = None, timestamp: str = None) -> None:
        """
        Restore `target`'s `timestamp` snapshot back over the live
        files.
        """
        if timestamp is None:
            self._usage("restore")
        memory_target = self._resolve_backup_target(target)
        label = self._backup_label(memory_target)
        available = self._available_backups(memory_target)
        if not available:
            self._fail(f"no backups found for '{label}'.")
        timestamp = self._resolve_backup_timestamp(available, timestamp)

        src_dir = self._backup_dir(memory_target) / timestamp
        sources = self._backup_sources(memory_target)
        restored = []
        for name, dest in sources.items():
            src = src_dir / name
            if src.exists():
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
                restored.append(name)
        self._ok(
            "restore",
            message=(
                f"RESTORED {label} from {timestamp} -> "
                f"restored: {', '.join(sorted(restored))}"
            ),
        )

    def remove(self, target: str = None, which: str = "latest") -> None:
        """
        Delete `target`'s `which` snapshot (default: the newest) or
        every snapshot (`which="all"`).
        """
        memory_target = self._resolve_backup_target(target)
        label = self._backup_label(memory_target)
        backup_dir = self._backup_dir(memory_target)
        available = self._available_backups(memory_target)
        if not available:
            self._fail(f"no backups found for '{label}'.")

        if which == "all":
            shutil.rmtree(backup_dir)
            self._ok("remove", message=f"DELETED all {len(available)} backup(s) "
                                        f"for '{label}'.")
            return

        timestamp = self._resolve_backup_timestamp(available, which)
        shutil.rmtree(backup_dir / timestamp)
        self._ok("remove", message=f"DELETED backup {label}/{timestamp}.")


    # Private Methods

    def _resolve_backup_target(self, target):
        if target:
            sid = resolve_session_or_exit(target)
        else:
            sid = os.environ.get("SESSION_ID", "").strip()
            if not sid:
                self._fail("no target given and no session attached.")
        session = _parse(session_file(sid))
        if not session.get("target_kind"):
            self._fail(f"session {sid} has no project/repository target configured.")
        return self._edit(resolve_memory_target, session)

    def _backup_label(self, memory_target) -> str:
        if memory_target.kind == "repository":
            return f"repository/{memory_target.repository_ids[0]}"
        label = f"project/{memory_target.project_id}"
        if memory_target.subproject_id:
            label += f"/{memory_target.subproject_id}"
        return label

    def _backup_dir(self, memory_target) -> Path:
        return BACKUPS_DIR / self._backup_label(memory_target)

    def _backup_sources(self, memory_target) -> dict:
        sources = {}
        if memory_target.project_path:
            sources[memory_target.project_path.name] = memory_target.project_path
        for repo_id, path in zip(
            memory_target.repository_ids, memory_target.repository_paths,
        ):
            sources[f"{repo_id}--{path.name}"] = path
        return sources

    def _available_backups(self, memory_target) -> list:
        backup_dir = self._backup_dir(memory_target)
        if not backup_dir.exists():
            return []
        return sorted(
            (p.name for p in backup_dir.iterdir() if p.is_dir()), reverse=True,
        )

    def _resolve_backup_timestamp(self, available: list, token: str) -> str:
        if token == "latest":
            return available[0]
        matches = [ts for ts in available if ts.startswith(token)]
        return require_unique_match(matches, "backup", token)
