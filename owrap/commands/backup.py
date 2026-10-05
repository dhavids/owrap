import shutil
import sys
import time

from ..utils.match import require_unique_match
from ..utils.paths import BACKUPS_DIR, resolve_memory_project_paths, get_todo_file_path

FILE_KINDS = ("memory", "projects", "todo")


def _research_file_paths(research: str) -> dict:
    """
    Return `{kind: path}` for a research's memory/projects/todo files —
    `path` is None for a kind that can't be resolved (research_root unset).
    """
    memory_path, projects_path = resolve_memory_project_paths(research)
    try:
        todo_path = get_todo_file_path(research)
    except ValueError:
        todo_path = None
    return {"memory": memory_path, "projects": projects_path, "todo": todo_path}


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
    Snapshot a research's memory/projects/todo files (item: backup/retrieve)
    — a manual safety net against the background dispatch (items 14-16)
    writing something wrong, kept under OWRAP_HOME, never in the research
    directory itself.
    """

    def run(self, research: str):
        """
        Copy every existing memory/projects/todo file for `research` into
        a new timestamped snapshot directory.
        """
        sources = _research_file_paths(research)
        existing = {k: p for k, p in sources.items() if p and p.exists()}
        if not existing:
            print(
                f"No memory/projects/todo files found for research '{research}' "
                "— nothing to back up.",
            )
            sys.exit(1)

        timestamp = time.strftime("%Y%m%dT%H%M%S")
        dest_dir = BACKUPS_DIR / research / timestamp
        dest_dir.mkdir(parents=True, exist_ok=True)
        for kind, src in existing.items():
            shutil.copy2(src, dest_dir / f"{kind}.md")

        print(f"BACKUP {research} -> {dest_dir} ({', '.join(sorted(existing))})")


class RetrieveRunner:
    """
    Restore a research's memory/projects/todo files from a backup taken by
    `owrap backup` — distinct from `owrap restore`, which restores a
    trashed *session*, not a file backup.
    """

    def run(self, research: str, timestamp: str = None):
        """
        List available backups for `research` if `timestamp` is omitted;
        otherwise restore that snapshot back over the live files —
        `timestamp` may be `"latest"` or an unambiguous prefix.
        """
        research_dir = BACKUPS_DIR / research
        available = (
            sorted((p.name for p in research_dir.iterdir() if p.is_dir()), reverse=True)
            if research_dir.exists() else []
        )
        if not available:
            print(f"No backups found for research '{research}'.")
            sys.exit(1)

        if timestamp is None:
            print(f"Available backups for '{research}' (newest first):")
            for ts in available:
                print(f"  {ts}")
            print(
                f"Run `owrap retrieve {research} <timestamp>` or "
                f"`owrap retrieve {research} latest` to restore one.",
            )
            return

        timestamp = _resolve_backup_timestamp(available, timestamp)

        src_dir = research_dir / timestamp
        dests = _research_file_paths(research)
        restored = []
        for kind, dest in dests.items():
            src = src_dir / f"{kind}.md"
            if src.exists() and dest:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
                restored.append(kind)

        print(
            f"RETRIEVED {research} from {timestamp} -> "
            f"restored: {', '.join(sorted(restored))}",
        )


class DeleteBackupRunner:
    """
    Delete one or all of a research's `owrap backup` snapshots — the
    supported way to clean these up instead of `rm -rf`ing them directly.
    """

    def run(self, research: str, which: str = "latest"):
        """
        `which="latest"` (default) deletes only the newest snapshot;
        `which="all"` deletes every snapshot for `research`; anything else
        is an unambiguous timestamp prefix to delete.
        """
        research_dir = BACKUPS_DIR / research
        available = (
            sorted((p.name for p in research_dir.iterdir() if p.is_dir()), reverse=True)
            if research_dir.exists() else []
        )
        if not available:
            print(f"No backups found for research '{research}'.")
            sys.exit(1)

        if which == "all":
            shutil.rmtree(research_dir)
            print(f"DELETED all {len(available)} backup(s) for '{research}'.")
            return

        timestamp = _resolve_backup_timestamp(available, which)

        shutil.rmtree(research_dir / timestamp)
        print(f"DELETED backup {research}/{timestamp}.")
