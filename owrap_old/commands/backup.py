import os
import shutil
import sys
import time
from pathlib import Path

from owrap.utils.match import require_unique_match
from owrap.utils.memory.records import resolve_memory_target
from owrap.utils.paths import BACKUPS_DIR
from owrap.utils.session.resolver import _parse, resolve_session_or_exit, session_file


def _resolve_backup_target(target):
    """
    Resolve a session id/project/subproject/repository name (or the
    currently attached session, if `target` is empty) to its MemoryTarget.
    """
    if target:
        sid = resolve_session_or_exit(target)
    else:
        sid = os.environ.get("SESSION_ID", "").strip()
        if not sid:
            print("ERROR: no target given and no session attached.")
            sys.exit(2)
    session = _parse(session_file(sid))
    if not session.get("target_kind"):
        print(f"ERROR: session {sid} has no project/repository target configured.")
        sys.exit(2)
    try:
        memory_target = resolve_memory_target(session)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}")
        sys.exit(2)
    return memory_target


def _backup_label(memory_target) -> str:
    """
    Return the human-readable backup key for a MemoryTarget.
    """
    if memory_target.kind == "repository":
        return f"repository/{memory_target.repository_ids[0]}"
    label = f"project/{memory_target.project_id}"
    if memory_target.subproject_id:
        label += f"/{memory_target.subproject_id}"
    return label


def _backup_dir(memory_target) -> Path:
    return BACKUPS_DIR / _backup_label(memory_target)


def _backup_sources(memory_target) -> dict:
    """
    Return `{filename: path}` for every Markdown record a MemoryTarget
    covers -- its own project/subproject file, if any, plus each linked
    repository's record, prefixed with the repository id to avoid name
    collisions between repositories that share a main filename.
    """
    sources = {}
    if memory_target.project_path:
        sources[memory_target.project_path.name] = memory_target.project_path
    for repo_id, path in zip(
        memory_target.repository_ids, memory_target.repository_paths,
    ):
        sources[f"{repo_id}--{path.name}"] = path
    return sources


def _available_backups(memory_target) -> list:
    backup_dir = _backup_dir(memory_target)
    if not backup_dir.exists():
        return []
    return sorted((p.name for p in backup_dir.iterdir() if p.is_dir()), reverse=True)


def _resolve_backup_timestamp(available: list, token: str) -> str:
    """
    Resolve `token` to one backup timestamp from `available`: `"latest"`
    is the newest; anything else is a prefix, resolved via
    `require_unique_match` (exits with an AMBIGUOUS listing if it matches
    more than one, or an error if it matches none).
    """
    if token == "latest":
        return available[0]
    matches = [ts for ts in available if ts.startswith(token)]
    return require_unique_match(matches, "backup", token)


class BackupRunner:
    """
    Snapshot a project/subproject/repository's Markdown records (item:
    backup/retrieve) -- a manual safety net against the background
    dispatch (items 14-16) writing something wrong, kept under
    OWRAP_HOME, never alongside the records themselves.
    """

    def run(self, target: str = None):
        """
        Copy every record file a target covers into a new timestamped
        snapshot directory.
        """
        memory_target = _resolve_backup_target(target)
        label = _backup_label(memory_target)
        sources = _backup_sources(memory_target)
        existing = {name: p for name, p in sources.items() if p.exists()}
        if not existing:
            print(f"No record files found for '{label}' — nothing to back up.")
            sys.exit(1)

        timestamp = time.strftime("%Y%m%dT%H%M%S")
        dest_dir = _backup_dir(memory_target) / timestamp
        dest_dir.mkdir(parents=True, exist_ok=True)
        for name, src in existing.items():
            shutil.copy2(src, dest_dir / name)

        print(f"BACKUP {label} -> {dest_dir} ({', '.join(sorted(existing))})")


class RetrieveRunner:
    """
    Restore a target's record files from a backup taken by `owrap backup`
    -- distinct from `owrap restore`, which restores a trashed *session*,
    not a file backup.
    """

    def run(self, target: str = None, timestamp: str = None):
        """
        List available backups for the target if `timestamp` is omitted;
        otherwise restore that snapshot back over the live files --
        `timestamp` may be `"latest"` or an unambiguous prefix.
        """
        memory_target = _resolve_backup_target(target)
        label = _backup_label(memory_target)
        available = _available_backups(memory_target)
        if not available:
            print(f"No backups found for '{label}'.")
            sys.exit(1)

        if timestamp is None:
            print(f"Available backups for '{label}' (newest first):")
            for ts in available:
                print(f"  {ts}")
            print(
                f"Run `owrap retrieve {target or label} <timestamp>` or "
                f"`owrap retrieve {target or label} latest` to restore one.",
            )
            return

        timestamp = _resolve_backup_timestamp(available, timestamp)

        src_dir = _backup_dir(memory_target) / timestamp
        sources = _backup_sources(memory_target)
        restored = []
        for name, dest in sources.items():
            src = src_dir / name
            if src.exists():
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
                restored.append(name)

        print(
            f"RETRIEVED {label} from {timestamp} -> "
            f"restored: {', '.join(sorted(restored))}",
        )


class DeleteBackupRunner:
    """
    Delete one or all of a target's `owrap backup` snapshots -- the
    supported way to clean these up instead of `rm -rf`ing them directly.
    """

    def run(self, target: str = None, which: str = "latest"):
        """
        `which="latest"` (default) deletes only the newest snapshot;
        `which="all"` deletes every snapshot for the target; anything else
        is an unambiguous timestamp prefix to delete.
        """
        memory_target = _resolve_backup_target(target)
        label = _backup_label(memory_target)
        backup_dir = _backup_dir(memory_target)
        available = _available_backups(memory_target)
        if not available:
            print(f"No backups found for '{label}'.")
            sys.exit(1)

        if which == "all":
            shutil.rmtree(backup_dir)
            print(f"DELETED all {len(available)} backup(s) for '{label}'.")
            return

        timestamp = _resolve_backup_timestamp(available, which)

        shutil.rmtree(backup_dir / timestamp)
        print(f"DELETED backup {label}/{timestamp}.")
