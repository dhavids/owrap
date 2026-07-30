import shutil
import time
from datetime import datetime
from pathlib import Path

from ..constants import TRASH_RETENTION_DAYS
from .paths import (
    TRASH_DIR, SESSIONS_DIR, RUNTIME_DIR, DOCS_DIR,
    session_dir, _read_config,
)


def move_to_trash(session_id: str) -> Path:
    """Move a session's .session file, docs tree, runtime tree, and context files into
    .trash/[session_id]/ instead of deleting them. Returns the trash directory path.
    Safe to call even if some/all pieces don't exist (moves whichever are present)."""
    trash_dir = TRASH_DIR / session_id
    trash_dir.mkdir(parents=True, exist_ok=True)

    session_file = SESSIONS_DIR / f"{session_id}.session"
    if session_file.exists():
        shutil.move(str(session_file), str(trash_dir / "session"))

    sdir = session_dir(session_id)
    if sdir.exists():
        shutil.move(str(sdir), str(trash_dir / "docs_sessions"))

    runtime = RUNTIME_DIR / session_id
    if runtime.exists():
        shutil.move(str(runtime), str(trash_dir / "runtime"))

    context_dest = trash_dir / "context"
    for suffix in (".md", ".lock"):
        p = DOCS_DIR / f"context_{session_id}{suffix}"
        if p.exists():
            context_dest.mkdir(parents=True, exist_ok=True)
            shutil.move(str(p), str(context_dest / p.name))

    (trash_dir / "trashed_at").write_text(datetime.now().isoformat())
    return trash_dir


def restore_from_trash(session_id: str) -> None:
    """Move a trashed session's files back to their live locations.
    Raises FileNotFoundError if no such trashed session exists."""
    trash_dir = TRASH_DIR / session_id
    if not trash_dir.exists():
        raise FileNotFoundError(f"no trashed session '{session_id}' found in {TRASH_DIR}")

    session_file = trash_dir / "session"
    if session_file.exists():
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        shutil.move(str(session_file), str(SESSIONS_DIR / f"{session_id}.session"))

    docs_src = trash_dir / "docs_sessions"
    if docs_src.exists():
        shutil.move(str(docs_src), str(session_dir(session_id)))

    runtime_src = trash_dir / "runtime"
    if runtime_src.exists():
        shutil.move(str(runtime_src), str(RUNTIME_DIR / session_id))

    context_src = trash_dir / "context"
    if context_src.exists():
        for f in context_src.iterdir():
            shutil.move(str(f), str(DOCS_DIR / f.name))

    shutil.rmtree(trash_dir, ignore_errors=True)


def sweep_trash(retention_days: float | None = None) -> int:
    """Permanently delete trashed sessions older than retention_days (config key
    'trash_retention_days', default TRASH_RETENTION_DAYS). Returns count removed."""
    if not TRASH_DIR.exists():
        return 0
    if retention_days is None:
        retention_days = float(
            _read_config().get("trash_retention_days", TRASH_RETENTION_DAYS)
        )
    cutoff = time.time() - (retention_days * 86400)
    removed = 0
    for entry in TRASH_DIR.iterdir():
        if not entry.is_dir():
            continue
        marker = entry / "trashed_at"
        trashed_at = None
        if marker.exists():
            try:
                trashed_at = datetime.fromisoformat(
                    marker.read_text().strip()
                ).timestamp()
            except Exception:
                trashed_at = None
        if trashed_at is None:
            trashed_at = entry.stat().st_mtime
        if trashed_at < cutoff:
            shutil.rmtree(entry, ignore_errors=True)
            removed += 1
    return removed
