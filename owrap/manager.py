import json
import logging
import os
import re
import subprocess
import time
import tempfile
from pathlib import Path

from .utils.terminal import Terminal
from .utils.logger import get_logger
from .utils.paths import TASKS_DIR, RUN_OUTPUT_DIR, STATE_FILE, SESSION_DIR, DOCS_DIR
from .utils.paths import RUN_LOG, EXEC_LOG, READ_LOG, INPUT_FILE
from .utils.paths import session_log, session_input


class Manager:
    TASKS_DIR = TASKS_DIR
    OUTPUT_DIR = RUN_OUTPUT_DIR
    STATE_FILE = STATE_FILE

    def __init__(self):
        self._t_invocation = time.time()
        self._t_cmd_start = None
        self._t_cmd_end = None
        self._log_file = None
        self._logger = None
        self.session_id = os.environ.get("OWRAP_SESSION", "")
        self.research = os.environ.get("OWRAP_RESEARCH", "")
        SESSION_DIR.mkdir(parents=True, exist_ok=True)
        self.TASKS_DIR.mkdir(parents=True, exist_ok=True)
        self.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        self._resolve_log_file()
        self.cleanup_done_tasks()
        self._housekeeping()

    @property
    def run_log_path(self) -> Path:
        return session_log(RUN_LOG, self.session_id)

    @property
    def exec_log_path(self) -> Path:
        return session_log(EXEC_LOG, self.session_id)

    @property
    def read_log_path(self) -> Path:
        return session_log(READ_LOG, self.session_id)

    @property
    def input_path(self) -> Path:
        return session_input(self.session_id)

    def _resolve_log_file(self):
        """Set up log_file: reuse if server PID alive, new if not."""
        state = self._read_state()
        if state is None:
            self._log_file = None
            return
        pid = state.get("pid")
        if pid is not None:
            try:
                os.kill(pid, 0)
                self._log_file = state.get("log_file")
                return
            except OSError:
                pass
        self._log_file = str(SESSION_DIR / f"owrap_{pid or 'new'}.log")

    def _read_state(self):
        try:
            with open(self.STATE_FILE) as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    def _write_state(self, state):
        dir_path = os.path.dirname(self.STATE_FILE)
        os.makedirs(dir_path, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=dir_path, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(state, f)
            os.rename(tmp_path, self.STATE_FILE)
        except Exception:
            os.unlink(tmp_path)
            raise

    def start(self, port=4096):
        SESSION_DIR.mkdir(parents=True, exist_ok=True)
        self._kill_port_occupant(port)
        tmp_log = SESSION_DIR / f"owrap_start_{int(time.time())}.log"
        log_fd = open(tmp_log, "w")
        proc = subprocess.Popen(
            ["opencode", "serve", "--port", str(port)],
            stdout=log_fd,
            stderr=log_fd,
            start_new_session=True,
            close_fds=True,
        )
        log_fd.close()
        pid = proc.pid
        url = None
        deadline = time.time() + 15.0
        while time.time() < deadline:
            time.sleep(0.2)
            try:
                content = tmp_log.read_text(errors="replace")
                match = re.search(r"https?://\S+", content)
                if match:
                    url = match.group().rstrip()
                    break
            except OSError:
                pass
            if proc.poll() is not None:
                raise RuntimeError("opencode serve exited before producing a URL")
        if url is None:
            proc.terminate()
            raise RuntimeError("opencode serve did not produce a URL within 15s")
        log_file = str(SESSION_DIR / f"owrap_{pid}.log")
        tmp_log.rename(log_file)
        self._log_file = log_file
        state = {"pid": pid, "url": url, "port": port, "log_file": log_file, "tasks": {}}
        self._write_state(state)
        if self._logger:
            self._logger.info("server started pid=%d url=%s", pid, url)
        return url

    def stop(self):
        state = self._read_state()
        if state is None:
            if self._logger:
                self._logger.info("stop: no server state found")
            return
        pid = state.get("pid")
        if pid is not None:
            try:
                os.kill(pid, 15)
                if self._logger:
                    self._logger.info("server stopped pid=%d", pid)
                deadline = time.time() + 5.0
                escalated = False
                while time.time() < deadline:
                    try:
                        os.kill(pid, 0)
                    except OSError:
                        break
                    if not escalated and time.time() - (deadline - 5.0) > 2.0:
                        try:
                            os.kill(pid, 9)
                            escalated = True
                        except OSError:
                            break
                    time.sleep(0.1)
            except OSError:
                if self._logger:
                    self._logger.info("stop: server pid=%s already gone", pid)
        try:
            os.unlink(self.STATE_FILE)
        except OSError:
            pass

    def _pid_alive(self, pid):
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def _find_port_pids(self, port):
        """Return PIDs listening on port by reading /proc/net/tcp (no external tools)."""
        hex_port = format(port, '04X')
        inodes = set()
        for tcp_file in ('/proc/net/tcp', '/proc/net/tcp6'):
            try:
                with open(tcp_file) as f:
                    for line in f:
                        parts = line.split()
                        if len(parts) < 10:
                            continue
                        local_addr = parts[1]
                        state = parts[3]
                        inode = parts[9]
                        if state == '0A':  # LISTEN
                            port_hex = local_addr.split(':')[-1].upper()
                            if port_hex == hex_port:
                                inodes.add(inode)
            except OSError:
                pass
        if not inodes:
            return []
        pids = []
        try:
            for entry in os.listdir('/proc'):
                if not entry.isdigit():
                    continue
                try:
                    fd_dir = f'/proc/{entry}/fd'
                    for fd in os.listdir(fd_dir):
                        try:
                            link = os.readlink(f'{fd_dir}/{fd}')
                            if link.startswith('socket:[') and link[8:-1] in inodes:
                                pids.append(int(entry))
                                break
                        except OSError:
                            pass
                except OSError:
                    pass
        except OSError:
            pass
        return pids

    def _kill_port_occupant(self, port):
        """Kill any process occupying the given port (orphan cleanup)."""
        pids = self._find_port_pids(port)
        for pid in pids:
            try:
                os.kill(pid, 15)
            except OSError:
                pass
        if pids:
            deadline = time.time() + 3.0
            while time.time() < deadline:
                if not any(self._pid_alive(p) for p in pids):
                    break
                time.sleep(0.1)
            for pid in pids:
                try:
                    os.kill(pid, 9)
                except OSError:
                    pass
            time.sleep(0.2)
            if self._logger:
                self._logger.info("kill_port_occupant: cleared pids=%s port=%d", pids, port)

    def get_url(self):
        state = self._read_state()
        if state is None:
            return None
        pid = state.get("pid")
        if pid is None:
            return None
        try:
            os.kill(pid, 0)
        except OSError:
            return None
        return state.get("url")

    def get_server_url(self):
        """Alias for get_url, used by BaseRunner."""
        return self.get_url()

    def get_logger(self, name: str = "owrap", level: str = "INFO") -> logging.Logger:
        """Create a logger using the manager's log_file path."""
        return get_logger(name, log_path=self._log_file, level=level)

    def set_logger(self, logger: logging.Logger):
        self._logger = logger

    def ensure_running(self, port=4096):
        url = self.get_url()
        if url is not None:
            if self._logger:
                self._logger.debug("ensure_running: server alive url=%s", url)
            return url
        if self._logger:
            self._logger.debug("ensure_running: server not running, starting")
        return self.start(port=port)

    def is_running(self):
        return self.get_url() is not None

    def t_cmd_start(self):
        self._t_cmd_start = time.time()

    def t_cmd_end(self):
        self._t_cmd_end = time.time()

    def log_time(self, log_time=True):
        if not self._t_cmd_start or not self._t_cmd_end:
            return
        opencode = self._t_cmd_end - self._t_cmd_start
        total = self._t_cmd_end - self._t_invocation
        preprocess = self._t_cmd_start - self._t_invocation
        if log_time:
            if preprocess > 0.05:
                print(f"[timing] preprocess={preprocess:.1f}s  opencode={opencode:.1f}s  total={total:.1f}s")
            else:
                print(f"[timing] opencode={opencode:.1f}s  total={total:.1f}s")

    def wait_for_input_clear(self, input_path, timeout=30, interval=1):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not input_path.exists() or input_path.stat().st_size == 0:
                return True
            time.sleep(interval)
        return False

    def next_task_id(self):
        max_n = 0
        if self.TASKS_DIR.exists():
            for path in self.TASKS_DIR.glob("task*.md"):
                match = re.match(r"task(\d+)\.md", path.name)
                if match:
                    n = int(match.group(1))
                    if n > max_n:
                        max_n = n
        return max_n + 1

    def register_task(self, task_id):
        state = self._read_state() or {}
        tasks = state.setdefault("tasks", {})
        tasks[str(task_id)] = {"status": "active", "invocation_time": self._t_invocation}
        self._write_state(state)

    def complete_task(self, task_id):
        state = self._read_state()
        if state is None:
            return
        tasks = state.setdefault("tasks", {})
        entry = tasks[str(task_id)]
        if isinstance(entry, str):
            entry = {"status": entry, "invocation_time": self._t_invocation}
        entry["status"] = "done"
        if self._t_cmd_start is not None and self._t_cmd_end is not None:
            entry["cmd_start"] = self._t_cmd_start
            entry["cmd_end"] = self._t_cmd_end
            entry["duration_s"] = round(self._t_cmd_end - self._t_cmd_start, 3)
            entry["total_s"] = round(self._t_cmd_end - entry["invocation_time"], 3)
        tasks[str(task_id)] = entry
        self._write_state(state)

    def cleanup_done_tasks(self):
        state = self._read_state()
        if state is None:
            return
        pid = state.get("pid")
        server_alive = False
        if pid is not None:
            try:
                os.kill(pid, 0)
                server_alive = True
            except OSError:
                pass
        tasks = state.get("tasks", {})
        to_remove = []
        for task_id, entry in tasks.items():
            status = entry if isinstance(entry, str) else entry.get("status", "active")
            if status == "done" or not server_alive:
                to_remove.append(task_id)
        for task_id in to_remove:
            n = int(task_id)
            (self.TASKS_DIR / f"task{n}.md").unlink(missing_ok=True)
            (self.OUTPUT_DIR / f"task{n}.log").unlink(missing_ok=True)
            for suffixed_log in self.OUTPUT_DIR.glob(f"task{n}_*.log"):
                suffixed_log.unlink(missing_ok=True)
            del tasks[task_id]
        self._write_state(state)

    def _housekeeping(self):
        sessions_dir = Path.home() / ".owrap" / "sessions"
        if not sessions_dir.exists():
            return
        active_ids = set()
        for sf in sessions_dir.glob("*.session"):
            try:
                for line in sf.read_text().splitlines():
                    if line.startswith("session_id="):
                        active_ids.add(line.split("=", 1)[1].strip())
            except Exception:
                pass
        if not active_ids:
            return
        for f in self.TASKS_DIR.glob("input_*.md"):
            sid = f.stem[len("input_"):]
            if sid and sid not in active_ids:
                f.unlink(missing_ok=True)
        for log_base in [RUN_LOG, EXEC_LOG, READ_LOG]:
            prefix = log_base.stem + "_"
            for f in log_base.parent.glob(f"{log_base.stem}_*.md"):
                sid = f.stem[len(prefix):]
                if sid and sid not in active_ids:
                    f.unlink(missing_ok=True)
        for f in DOCS_DIR.glob("plan_*.md"):
            sid = f.stem[len("plan_"):]
            if sid and sid not in active_ids:
                f.unlink(missing_ok=True)
