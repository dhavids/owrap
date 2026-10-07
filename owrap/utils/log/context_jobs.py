"""
Persistent status records for background context work.
"""

import json
import os
import tempfile
import time
from pathlib import Path
from uuid import uuid4

from ...constants import RECENT_TASK_RETENTION_S
from ..filelock import file_lock
from .. import paths
from . import rtlog


def create(session_id: str, window_id: str, kind: str) -> Path:
    """
    Create one queued context job and return its directory.
    """
    job_dir = paths.session_ctx_jobs_dir(session_id) / uuid4().hex[:10]
    job_dir.mkdir(parents=True)
    update(
        job_dir, job_id=job_dir.name, session_id=session_id,
        window_id=window_id, kind=kind, status="queued",
        queued=time.time(), log_path=str(job_dir / "output.log"),
        transcript_path=str(job_dir / "transcript.txt"),
        result_path=str(job_dir / "output.md"),
    )
    rtlog.log("ctx.queued", job_id=job_dir.name, kind=kind, session_id=session_id)
    return job_dir


def update(job_dir: Path, **fields) -> dict:
    """
    Atomically merge fields into one job status record.
    """
    status_path = job_dir / "status.json"
    with file_lock(job_dir / "status.lock"):
        data = json.loads(status_path.read_text()) if status_path.exists() else {}
        data.update(fields)
        data["updated"] = time.time()
        fd, temp_path = tempfile.mkstemp(dir=job_dir, prefix=".status.")
        try:
            with os.fdopen(fd, "w") as stream:
                json.dump(data, stream)
            os.replace(temp_path, status_path)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
    if "stage" in fields:
        rtlog.log(
            "ctx.progress", job_id=job_dir.name,
            session_id=data.get("session_id"), kind=data.get("kind"),
            stage=data.get("stage"), model=data.get("model"),
        )
    return data


def finish(job_dir: Path, rc: int) -> None:
    """
    Record the completed worker result.
    """
    status = "succeeded" if rc == 0 else "failed"
    data = update(job_dir, status=status, rc=rc, finished=time.time())
    rtlog.log(
        "ctx.done", job_id=job_dir.name, kind=data.get("kind"),
        session_id=data.get("session_id"), rc=rc,
        log_path=data.get("log_path"), result_path=data.get("result_path"),
        output_snippet=tail(Path(data["log_path"]), limit=320),
    )


def tail(path: Path, limit: int = 320) -> str:
    """
    Read the last printable characters from a worker log.
    """
    try:
        with path.open("rb") as stream:
            stream.seek(0, os.SEEK_END)
            stream.seek(max(0, stream.tell() - limit * 4))
            data = stream.read().decode(errors="replace")
        clean = " ".join(data.split())
        if len(clean) <= limit:
            return clean
        snippet = clean[-limit:]
        first_space = snippet.find(" ")
        return snippet[first_space + 1:] if first_space >= 0 else snippet
    except OSError:
        return ""


def recent(session_id: str | None = None, limit: int = 8) -> list[dict]:
    """
    Read active and recent context jobs from session storage.
    """
    jobs = []
    root = paths.SESSIONS_DIR
    if not root.exists():
        return jobs
    status_paths = list(root.glob("*/ctx/jobs/*/status.json"))
    status_paths.extend(root.glob("*/ctx/*/jobs/*/status.json"))
    for status_path in status_paths:
        try:
            data = json.loads(status_path.read_text())
            if session_id and data.get("session_id") != session_id:
                continue
            data["job_dir"] = str(status_path.parent)
            jobs.append(data)
        except (OSError, ValueError):
            continue
    active = []
    done = []
    now = time.time()
    for job in jobs:
        status = job.get("status")
        pid = job.get("pid")
        alive = False
        if isinstance(pid, int) and pid > 0:
            try:
                os.kill(pid, 0)
                alive = True
            except OSError:
                pass
        recent_queue = now - job.get("queued", 0) < 5
        if status in ("queued", "running") and (alive or recent_queue):
            active.append(job)
            continue
        ended = job.get("finished", job.get("updated", job.get("queued", 0)))
        if now - ended <= RECENT_TASK_RETENTION_S:
            done.append(job)
    active.sort(key=lambda job: job.get("queued", 0), reverse=True)
    done.sort(
        key=lambda job: job.get("finished", job.get("updated", 0)),
        reverse=True,
    )
    return active + done[:limit]
