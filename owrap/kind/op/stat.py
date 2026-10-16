import json
import os
import time
from pathlib import Path

from . import Op
from ...dispatch import work
from ...dispatch.process import is_alive
from ...session.resolver import (
    _parse as _parse_session, session_files, session_label,
)
from ...utils.dispatch.pool import _active_load, get_pool
from ...utils.log import context_jobs
from ...utils.paths import (
    DAEMON_PID_FILE, DAEMON_STATE_FILE, RECENTLY_DONE_DIR, RUNNING_DIR,
    RUNTIME_LOG, SERVER_LOGS_DIR, SESSIONS_DIR, SESSION_DIR, STATS_FILE,
    _read_config, session_input,
)
from ...utils.parser.text import age_str


def _print_tasks(tasks, show_session: bool = True, indent: str = "  ") -> None:
    for t in tasks:
        print(f"{indent}{work.format_task_status(t, show_session=show_session)}")


def _idle_budget(log_path: str, started: float):
    """
    This job's current kill deadline, in seconds since `started` --
    read from the heartbeat `Terminal.run` keeps next to the log,
    or None if the job hasn't produced output yet (or isn't ctx).
    """
    idle_path = Path(log_path).parent / "work" / "idle.json"
    if not idle_path.exists():
        return None
    try:
        heartbeat = json.loads(idle_path.read_text())
        return max(
            0,
            (heartbeat["last_data_time"] - started)
            + heartbeat["active_idle_timeout"],
        )
    except (OSError, ValueError, KeyError):
        return None


def _print_context_jobs(jobs, show_session: bool = True) -> None:
    for job in jobs:
        status = job.get("status", "unknown")
        pid = job.get("pid")
        if status in ("queued", "running"):
            recent = time.time() - job.get("queued", 0) < 5
            if not recent and (not pid or not is_alive(pid)):
                status = "stale/crashed"
        stage = job.get("stage", "")
        if status in ("queued", "running") and stage:
            status = f"{status} ({stage})"
        if status == "succeeded":
            status = "done(ok)"
        elif status == "failed":
            status = f"failed(rc={job.get('rc', '?')})"
        started = job.get("started") or job.get("queued") or time.time()
        ended = job.get("finished") or time.time()
        elapsed = max(0, ended - started)
        kind = job.get("kind", "ctx")
        sid = job.get("session_id", "?")
        job_id = job.get("job_id", "?")
        session = f"[{session_label(sid)}]  " if show_session else ""
        age = f"  {age_str(job['finished'])} ago" if job.get("finished") else ""
        log_path = job.get("log_path", "")
        budget = (
            _idle_budget(log_path, started)
            if log_path and not job.get("finished") else None
        )
        clock = f"{elapsed:.0f}s/{budget:.0f}s" if budget is not None else f"{elapsed:.0f}s"
        print(f"  {kind}  {session}{job_id}  {status}{age}  {clock}")
        if log_path:
            print(f"    output: {log_path}")
        transcript = job.get("transcript_path", "")
        if transcript:
            print(f"    transcript: {transcript}")


def _print_identity(data: dict) -> None:
    kind = data.get("target_kind", "")
    if kind == "project":
        print(f"    project:  {data.get('project_id', '?')}")
        subproject = data.get("subproject_id", "")
        if subproject:
            print(f"    sub:      {subproject}")
        return
    if kind == "repository":
        print(f"    repo:     {data.get('repository_id', '?')}")


def _load_tasks():
    running, done = [], []
    if RUNNING_DIR.exists():
        for f in sorted(RUNNING_DIR.iterdir()):
            try:
                data = json.loads(f.read_text())
                pid = data.get("pid")
                data["alive"] = bool(pid) and is_alive(pid)
                running.append(data)
            except Exception:
                pass
    if RECENTLY_DONE_DIR.exists():
        for f in sorted(RECENTLY_DONE_DIR.iterdir()):
            try:
                done.append(json.loads(f.read_text()))
            except Exception:
                pass
    return running, done


class Stat(Op):
    """
    Reports on the dispatch system as a whole -- daemon state, server
    pool, every running/recently-done task, context jobs, and every
    known session's identity -- the `owrap stat` command. No stored
    identity or live process of its own, acting on one implicit
    target (the whole dispatch system): `do` is the full report, `get`
    narrows it to one session's tasks and queue. Every per-task status
    line goes through `work.format_task_status`.
    """

    kind = "stat"

    usage = {
        "do": {
            "usage": "", "args": [], "examples": [""],
            "purpose": "Show sessions, types, recent tasks, live stages, and "
                   "server status",
            "group": "session",
        },
        "get": {
            "usage": "<session_id>",
            "args": [("session_id", "filter to one session's tasks/queue")],
            "examples": ["abc123"],
        },
    }


    # Public Methods

    def do(self) -> None:
        """
        Full stats/daemon/pool/session report.
        """
        work.cleanup_recently_done()
        self._full_report()

    def get(self, session_id: str = None) -> None:
        """
        One session's tasks and queue.
        """
        if session_id is None:
            self._usage("get")
        work.cleanup_recently_done()
        self._show_tasks(session_id)


    # Private Methods

    def _full_report(self) -> None:
        current_id = os.environ.get("CLAUDE_CODE_SESSION_ID", "")

        stats = None
        if STATS_FILE.exists():
            try:
                stats = json.loads(STATS_FILE.read_text())
            except Exception:
                pass

        banner = "=== OWRAP STATS ==="
        if stats and stats.get("dispatched", 0) > 0:
            dispatched = stats["dispatched"]
            succeeded = stats.get("succeeded", 0)
            failed = stats.get("failed", 0)
            stalled = stats.get("stalled", 0)
            if failed > 0 or stalled > 0:
                reliability = succeeded / dispatched * 100
                parts = []
                if failed > 0:
                    parts.append(f"{failed} failed")
                if stalled > 0:
                    parts.append(f"{stalled} stalled")
                detail = ", ".join(parts)
                banner = f"=== OWRAP STATS — {detail} ({reliability:.1f}%) ==="
        print(f"{banner}\n")

        self._print_daemon_status()

        pool = get_pool()
        running_tasks, done_tasks = _load_tasks()
        all_srv_urls = {entry.get("url") for entry in pool}

        if pool:
            self._print_pool(pool, running_tasks, done_tasks)
        else:
            print("  server: not started\n")

        self._print_dead_servers(running_tasks, done_tasks, all_srv_urls, pool)

        orphan_running = [t for t in running_tasks if not t.get("server_url")]
        orphan_done = [t for t in done_tasks if not t.get("server_url")]
        ctx_jobs = context_jobs.recent()
        if orphan_running or orphan_done or ctx_jobs:
            print("tasks:")
            _print_tasks(orphan_running)
            _print_tasks(orphan_done)
            _print_context_jobs(ctx_jobs)
            print()

        self._print_sessions(current_id)

    def _print_daemon_status(self) -> None:
        if DAEMON_PID_FILE.exists():
            try:
                kpid = int(DAEMON_PID_FILE.read_text().strip())
                os.kill(kpid, 0)
                ka_extra = ""
                if not _read_config().get("owrap_runner_enabled", True):
                    ka_extra = "  runner: disabled"
                elif DAEMON_STATE_FILE.exists():
                    try:
                        ks = json.loads(DAEMON_STATE_FILE.read_text())
                        idle_since = ks.get("idle_since")
                        if idle_since is not None:
                            ka_extra = f"  idle {time.time() - idle_since:.0f}s"
                        else:
                            ka_extra = "  active"
                    except Exception:
                        pass
                print(f"  daemon: pid={kpid} running{ka_extra}")
            except (ValueError, OSError):
                print("  daemon: stopped")
        else:
            print("  daemon: stopped")
        if RUNTIME_LOG.exists():
            sz = RUNTIME_LOG.stat().st_size
            print(f"  rtlog: {RUNTIME_LOG} ({sz // 1024} KB)")
        else:
            print(f"  rtlog: {RUNTIME_LOG} (empty)")
        print()

    def _print_pool(self, pool, running_tasks, done_tasks) -> None:
        n = len(pool)
        label = "server:" if n == 1 else f"servers ({n}):"
        print(f"  {label}")
        cfg = _read_config()
        idle_shutdown_s = float(cfg.get("idle_shutdown_s", 300))
        now = time.time()
        for i, entry in enumerate(pool):
            if i > 0:
                print()
            pid = entry.get("pid", "?")
            url = entry.get("url", "?")
            load = _active_load(url)
            last_used = entry.get("last_used", 0)
            if last_used:
                dies_in = max(0, idle_shutdown_s - (now - last_used))
                if load > 0:
                    dies_str = ""
                elif dies_in > 0:
                    dies_str = f"  dies in {dies_in:.0f}s"
                else:
                    dies_str = "  idle (kept alive)"
            else:
                dies_str = ""
            log_file = SERVER_LOGS_DIR / f"owrap_{pid}.log"
            log_str = f"  {log_file}" if log_file.exists() else ""
            print(f"    {url}  load={load}{dies_str}{log_str}")
            srv_running = [t for t in running_tasks if t.get("server_url") == url]
            srv_done = [t for t in done_tasks if t.get("server_url") == url]
            if srv_running or srv_done:
                print("      tasks:")
                _print_tasks(srv_running, indent="        ")
                _print_tasks(srv_done, indent="        ")
        print()

    def _print_dead_servers(self, running_tasks, done_tasks, all_srv_urls, pool) -> None:
        dead_urls = {}
        for t in running_tasks + done_tasks:
            url = t.get("server_url", "")
            if url and url not in all_srv_urls:
                dead_urls.setdefault(url, [])
        dead_urls_sorted = sorted(dead_urls.keys())
        if not dead_urls_sorted:
            return
        if not pool:
            print(f"  servers ({len(dead_urls_sorted)}):")
        for url in dead_urls_sorted:
            ghost_running = [t for t in running_tasks if t.get("server_url") == url]
            ghost_done = [t for t in done_tasks if t.get("server_url") == url]
            print(f"    {url}  [dead]")
            if ghost_running or ghost_done:
                print("      tasks:")
                _print_tasks(ghost_running, indent="        ")
                _print_tasks(ghost_done, indent="        ")
        print()

    def _print_sessions(self, current_id: str) -> None:
        metadata_files = []
        if SESSIONS_DIR.exists():
            metadata_files = sorted(
                session_files(), key=lambda p: p.stat().st_mtime, reverse=True,
            )

        if metadata_files:
            n = len(metadata_files)
            label = "session:" if n == 1 else f"sessions ({n}):"
            print(label)
            for sf in metadata_files:
                data = _parse_session(sf)
                sid = data.get("session_id") or sf.parent.name
                marker = "  [current]" if sid == current_id else ""
                age = age_str(sf.stat().st_mtime)
                print(f"  {sid}{marker}")
                print(f"    type:     {data.get('session_mode') or 'normal'}")
                _print_identity(data)
                print(f"    age:      {age}")
                print()
        else:
            print("  (no scoped sessions found)\n")

        global_session = SESSION_DIR / "session"
        if global_session.exists():
            data = _parse_session(global_session)
            age = age_str(global_session.stat().st_mtime)
            print("global (~/.owrap/session):")
            print(f"    session:  {data.get('session_id', '?')}")
            _print_identity(data)
            print(f"    age:      {age}")

    def _show_tasks(self, session_id: str) -> None:
        running, done = _load_tasks()
        running = [t for t in running if t.get("session_id") == session_id]
        done = [t for t in done if t.get("session_id") == session_id]
        ctx_jobs = context_jobs.recent(session_id)

        all_sids = {t.get("session_id") for t in running + done if t.get("session_id")}
        all_sids.add(session_id)

        print(f"tasks [{session_label(session_id)}]:")
        if not running and not done and not ctx_jobs:
            print("  (no running or recently-done tasks)")
        else:
            _print_tasks(running, show_session=False)
            _print_tasks(done, show_session=False)
            _print_context_jobs(ctx_jobs, show_session=False)

        queued = []
        for sid in sorted(all_sids):
            try:
                qpath = session_input(sid)
                if qpath.exists() and qpath.read_text().strip():
                    queued.append(str(qpath))
            except Exception:
                pass
        if queued:
            print(f"  queue: {len(queued)} staged — {', '.join(queued)}")
        else:
            print("  queue: empty")
        print()
