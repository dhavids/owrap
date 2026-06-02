import fcntl
import json
import logging
import os
import re
import shlex
import subprocess
import time
import tempfile
from datetime import datetime
from pathlib import Path

from .utils.terminal import Terminal
from .utils.logger import get_logger
from .utils.paths import TASKS_DIR, RUN_OUTPUT_DIR, STATE_FILE, SESSION_DIR, SERVERS_DIR, DOCS_DIR, RUNNING_DIR
from .utils.paths import RUN_LOG, EXEC_LOG, READ_LOG, INPUT_FILE, _read_config, get_plan_path
from .utils.paths import session_log, session_input, context_path, context_lock_path


class Manager:
    TASKS_DIR = TASKS_DIR
    OUTPUT_DIR = RUN_OUTPUT_DIR
    STATE_FILE = STATE_FILE

    def __init__(self, port=None):
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
        config = _read_config()
        use_multi = config.get("use_multiple_servers", False)
        if port is not None and use_multi:
            SERVERS_DIR.mkdir(parents=True, exist_ok=True)
            self._state_file = str(SERVERS_DIR / f"{port}.json")
        elif port is None and use_multi:
            server_url = os.environ.get("OWRAP_SERVER_URL", "")
            if server_url:
                try:
                    p = int(server_url.rsplit(":", 1)[-1])
                    SERVERS_DIR.mkdir(parents=True, exist_ok=True)
                    self._state_file = str(SERVERS_DIR / f"{p}.json")
                except (ValueError, IndexError):
                    self._state_file = self.STATE_FILE
            else:
                # No env var: try session file first, then fall back to mtime scan
                found = None
                claude_sid = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
                if claude_sid:
                    sf = Path.home() / ".owrap" / "sessions" / f"{claude_sid}.session"
                    if sf.exists():
                        for line in sf.read_text().splitlines():
                            if line.startswith("server_url="):
                                url_from_file = line.split("=", 1)[1].strip()
                                try:
                                    p = int(url_from_file.rsplit(":", 1)[-1])
                                    SERVERS_DIR.mkdir(parents=True, exist_ok=True)
                                    candidate = SERVERS_DIR / f"{p}.json"
                                    if candidate.exists():
                                        data = json.loads(candidate.read_text())
                                        pid = data.get("pid")
                                        if pid:
                                            os.kill(pid, 0)
                                            found = str(candidate)
                                except (OSError, Exception):
                                    pass
                                break
                if found is None and SERVERS_DIR.exists():
                    for f in sorted(SERVERS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
                        try:
                            data = json.loads(f.read_text())
                            pid = data.get("pid")
                            if pid:
                                os.kill(pid, 0)
                                found = str(f)
                                break
                        except (OSError, Exception):
                            pass
                self._state_file = found if found else self.STATE_FILE
        else:
            self._state_file = self.STATE_FILE
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
            with open(self._state_file) as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    def _write_state(self, state):
        dir_path = os.path.dirname(self._state_file)
        os.makedirs(dir_path, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=dir_path, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(state, f)
            os.rename(tmp_path, self._state_file)
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
            os.unlink(self._state_file)
        except OSError:
            pass

    def _pid_alive(self, pid):
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def _server_responsive(self, url, timeout=3):
        import socket
        try:
            addr = url.replace("http://", "").replace("https://", "")
            parts = addr.rsplit(":", 1)
            host = parts[0]
            port = int(parts[1]) if len(parts) > 1 else 4096
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except (OSError, ValueError):
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
        url = state.get("url")
        if url and not self._server_responsive(url):
            if self._logger:
                self._logger.warning("get_url: pid=%s alive but port not responding, treating as down", pid)
            return None
        return url

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

    @staticmethod
    def sessions_per_server() -> dict:
        """Count sessions per server URL."""
        sessions_dir = Path.home() / ".owrap" / "sessions"
        counts = {}
        if sessions_dir.exists():
            for sf in sessions_dir.glob("*.session"):
                try:
                    for line in sf.read_text().splitlines():
                        if line.startswith("server_url="):
                            url = line.split("=", 1)[1].strip()
                            counts[url] = counts.get(url, 0) + 1
                except Exception:
                    pass
        return counts

    @staticmethod
    def list_servers() -> list:
        """Return list of all server state dicts (with 'alive' key)."""
        config = _read_config()
        use_multi = config.get("use_multiple_servers", False)
        servers = []
        seen_pids = set()
        seen_urls = set()
        if use_multi and SERVERS_DIR.exists():
            for f in sorted(SERVERS_DIR.glob("*.json")):
                try:
                    data = json.loads(f.read_text())
                    pid = data.get("pid")
                    if pid:
                        try:
                            os.kill(pid, 0)
                            data["alive"] = True
                            seen_pids.add(pid)
                            seen_urls.add(data.get("url", ""))
                            servers.append(data)
                        except OSError:
                            f.unlink(missing_ok=True)
                except Exception:
                    pass
        # Always check legacy manager.json — server may have written there (e.g. old shim, transition)
        try:
            with open(STATE_FILE) as f:
                data = json.load(f)
            pid = data.get("pid")
            url = data.get("url", "")
            if pid and pid not in seen_pids and url not in seen_urls:
                try:
                    os.kill(pid, 0)
                    data["alive"] = True
                except OSError:
                    data["alive"] = False
                servers.append(data)
        except Exception:
            pass
        if not servers:
            # Non-multi fallback already covered above; if empty show nothing
            pass
        return servers

    @staticmethod
    def get_or_start_server(logger=None):
        """Return (Manager_instance, url) for the session-assigned server."""
        config = _read_config()
        use_multi = config.get("use_multiple_servers", False)
        max_svrs = int(config.get("max_servers", 1))
        base_port = 4096
        if not use_multi:
            m = Manager()
            url = m.ensure_running(port=base_port)
            return m, url
        SERVERS_DIR.mkdir(parents=True, exist_ok=True)
        running = []
        for f in sorted(SERVERS_DIR.glob("*.json")):
            try:
                data = json.loads(f.read_text())
                pid = data.get("pid")
                port = data.get("port")
                url = data.get("url")
                if pid and port:
                    try:
                        os.kill(pid, 0)
                        running.append({"port": port, "url": url, "pid": pid})
                    except OSError:
                        pass
            except Exception:
                pass
        sess_counts = Manager.sessions_per_server()
        zero_session = [s for s in running if sess_counts.get(s["url"], 0) == 0]
        if zero_session:
            best = zero_session[0]
            return Manager(port=best["port"]), best["url"]
        if len(running) < max_svrs:
            used_ports = {s["port"] for s in running}
            port = next(p for p in range(base_port, base_port + max_svrs + 10) if p not in used_ports)
            m = Manager(port=port)
            url = m.start(port=port)
            return m, url
        else:
            running.sort(key=lambda s: sess_counts.get(s["url"], 0))
            best = running[0]
            return Manager(port=best["port"]), best["url"]

    @staticmethod
    def stop_all(logger=None):
        """Stop all running servers."""
        config = _read_config()
        use_multi = config.get("use_multiple_servers", False)
        if use_multi and SERVERS_DIR.exists():
            for f in SERVERS_DIR.glob("*.json"):
                try:
                    data = json.loads(f.read_text())
                    port = data.get("port")
                    if port:
                        Manager(port=port).stop()
                except Exception:
                    pass
        else:
            Manager().stop()

    @staticmethod
    def trim_idle_servers():
        """Kill all live servers that have 0 active sessions. Returns count killed."""
        config = _read_config()
        use_multi = config.get("use_multiple_servers", False)
        sess_counts = Manager.sessions_per_server()
        killed = 0
        if use_multi and SERVERS_DIR.exists():
            for f in sorted(SERVERS_DIR.glob("*.json")):
                try:
                    data = json.loads(f.read_text())
                    pid = data.get("pid")
                    port = data.get("port")
                    url = data.get("url", "")
                    if not pid or not port:
                        continue
                    try:
                        os.kill(pid, 0)
                    except OSError:
                        f.unlink(missing_ok=True)
                        continue
                    if sess_counts.get(url, 0) == 0:
                        try:
                            os.kill(pid, 15)
                            print(f"  killed idle server port={port} pid={pid}")
                            killed += 1
                        except OSError:
                            pass
                        f.unlink(missing_ok=True)
                except Exception:
                    pass
        try:
            with open(STATE_FILE) as f_st:
                data = json.load(f_st)
            pid = data.get("pid")
            url = data.get("url", "")
            port = data.get("port", "?")
            if pid:
                try:
                    os.kill(pid, 0)
                    if sess_counts.get(url, 0) == 0:
                        os.kill(pid, 15)
                        print(f"  killed idle server port={port} pid={pid}")
                        killed += 1
                        try:
                            os.unlink(STATE_FILE)
                        except OSError:
                            pass
                except OSError:
                    try:
                        os.unlink(STATE_FILE)
                    except OSError:
                        pass
        except Exception:
            pass
        if killed == 0:
            print("owrap trim: no idle servers found")
        else:
            print(f"owrap trim: killed {killed} idle server(s)")
        return killed

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

    @property
    def context_path(self) -> Path:
        return context_path(self.session_id)

    def create_context(self, url=None):
        cp = self.context_path
        config = _read_config()
        research_root = config.get("research_root", "")
        venv = config.get("venv", "")
        plan = str(get_plan_path(self.session_id)) if self.session_id else "none"
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        url = url or self.get_url() or ""
        if cp.exists():
            text = cp.read_text()
            for field, value in (
                ("session", self.session_id or "none"),
                ("research", self.research or "none"),
                ("server", url),
                ("plan", plan),
                ("last_updated", now),
            ):
                text = re.sub(rf"^{field}:.*$", f"{field}: {value}", text, flags=re.MULTILINE)
            cp.write_text(text)
            return
        content = (
            "## Session\n\n"
            f"session: {self.session_id or 'none'}\n"
            f"research: {self.research or 'none'}\n"
            f"server: {url}\n"
            f"plan: {plan}\n"
            "phase: 1\n"
            f"research_root: {research_root}\n"
            f"venv: {venv}\n"
            f"last_updated: {now}\n"
            "\n## Focus\n\n"
            "## Active Plan\n\n"
            "## Key Locations\n\n"
            "## Decisions\n\n"
            "## Environment\n\n"
            "## Frequent Files\n\n"
            "## Recent\n\n"
        )
        cp.parent.mkdir(parents=True, exist_ok=True)
        cp.write_text(content)

    def append_context_recent(self, title: str, rc: int, ctx: bool = True, kind: str = "msg"):
        cp = self.context_path
        lock = context_lock_path(self.session_id)
        if not cp.exists():
            return
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_WRONLY)
            fcntl.flock(fd, fcntl.LOCK_EX)
            try:
                text = cp.read_text()
                lines = text.splitlines()
                recent_idx = None
                for i, line in enumerate(lines):
                    if line.startswith("## Recent"):
                        recent_idx = i
                        break
                if recent_idx is None:
                    return
                now = datetime.now().strftime("%H:%M")
                now_full = datetime.now().strftime("%Y-%m-%d %H:%M")
                title_short = title[:60]
                ctx_str = "ctx=yes" if ctx else "ctx=no"
                new_entry = f"- {now} [{kind}] {title_short} (rc={rc}, {ctx_str})"
                # Update last_updated in Session header
                new_lines_pre = []
                for line in lines:
                    if line.startswith("last_updated:"):
                        new_lines_pre.append(f"last_updated: {now_full}")
                    else:
                        new_lines_pre.append(line)
                lines = new_lines_pre
                recent_lines = []
                for line in lines[recent_idx + 1:]:
                    if line.startswith("## "):
                        break
                    if line.strip():
                        recent_lines.append(line)
                recent_lines.insert(0, new_entry)
                recent_lines = recent_lines[:5]
                before = lines[:recent_idx + 1]
                after_start = recent_idx + 1 + len(lines[recent_idx + 1:]) - len(recent_lines)
                for i in range(recent_idx + 1, len(lines)):
                    if lines[i].startswith("## "):
                        after_start = i
                        break
                else:
                    after_start = len(lines)
                after = lines[after_start:]
                new_lines = before + recent_lines + [""] + after
                cp.write_text("\n".join(new_lines) + "\n")
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)
        except Exception:
            pass

    def update_frequent_files(self):
        cp = self.context_path
        lock = context_lock_path(self.session_id)
        read_log = self.read_log_path
        if not cp.exists() or not read_log.exists():
            return
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_WRONLY)
            fcntl.flock(fd, fcntl.LOCK_EX)
            try:
                content = read_log.read_text()
                counts = {}
                for line in content.splitlines():
                    match = re.search(r"—\s+(.+)$", line)
                    if match:
                        path_str = match.group(1).strip()
                        counts[path_str] = counts.get(path_str, 0) + 1
                top5 = sorted(
                    ((p, c) for p, c in counts.items() if Path(p).exists()),
                    key=lambda x: x[1], reverse=True
                )[:5]
                lines = cp.read_text().splitlines()
                freq_idx = None
                for i, line in enumerate(lines):
                    if line.startswith("## Frequent Files"):
                        freq_idx = i
                        break
                if freq_idx is None:
                    return
                next_section = len(lines)
                for i in range(freq_idx + 1, len(lines)):
                    if lines[i].startswith("## "):
                        next_section = i
                        break
                before = lines[:freq_idx + 1]
                after = lines[next_section:]
                new_lines = before + [f"- {path} ({count})" for path, count in top5] + [""] + after
                cp.write_text("\n".join(new_lines) + "\n")
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)
        except Exception:
            pass

    def refresh_context_plan(self, plan_path=None):
        """Update ## Active Plan section from the first 3 uncompleted steps in the active plan."""
        cp = self.context_path
        if not cp.exists():
            return
        if plan_path is None:
            plan_path = get_plan_path(self.session_id)
        plan_path = Path(plan_path)
        if not plan_path.exists():
            return
        plan_text = plan_path.read_text()
        steps = []
        in_active = False
        for line in plan_text.splitlines():
            if "## [ACTIVE]" in line:
                in_active = True
            elif line.startswith("## ") and in_active:
                break
            elif in_active and re.match(r"\d+\. \[ \]", line):
                steps.append(line.strip())
                if len(steps) >= 3:
                    break
        plan_snippet = "\n".join(steps) if steps else "(no active steps)"
        lock = context_lock_path(self.session_id)
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_WRONLY)
            fcntl.flock(fd, fcntl.LOCK_EX)
            try:
                text = cp.read_text()
                new_text = re.sub(
                    r"(## Active Plan\n).*?(\n## )",
                    lambda m: m.group(1) + "\n" + plan_snippet + "\n" + m.group(2),
                    text, flags=re.DOTALL
                )
                cp.write_text(new_text)
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)
        except Exception:
            pass

    def start_watchdog(self):
        import threading
        if not self.session_id:
            return
        def _watchdog_loop():
            while True:
                time.sleep(600)
                cp = self.context_path
                if not cp.exists():
                    continue
                try:
                    size = cp.stat().st_size
                    if size < 500:
                        continue
                    has_active = False
                    if RUNNING_DIR.exists():
                        for sentinel in RUNNING_DIR.glob(f"*_{self.session_id}*"):
                            has_active = True
                            break
                    if has_active:
                        continue
                    lock = context_lock_path(self.session_id)
                    fd = os.open(str(lock), os.O_CREAT | os.O_WRONLY)
                    fcntl.flock(fd, fcntl.LOCK_SH)
                    snapshot = cp.read_text()
                    mtime = cp.stat().st_mtime
                    fcntl.flock(fd, fcntl.LOCK_UN)
                    os.close(fd)
                    servers = Manager.sessions_per_server()
                    if not servers:
                        continue
                    least_busy_url = min(servers, key=servers.get)
                    prompt = f"Compress the following session context file. Keep all section headers. Condense entries to the most important facts. Preserve the structure. Return only the compressed content:\n\n{snapshot}"
                    cmd = f"opencode run --attach {least_busy_url} -- {shlex.quote(prompt)}"
                    result = Terminal(verbose=False).run(cmd, capture_output=True, print_output=False, timeout=60)
                    compressed = (result.get("stdout") or "").strip()
                    if not compressed:
                        continue
                    fd = os.open(str(lock), os.O_CREAT | os.O_WRONLY)
                    fcntl.flock(fd, fcntl.LOCK_EX)
                    try:
                        current_mtime = cp.stat().st_mtime
                        if current_mtime == mtime:
                            cp.write_text(compressed + "\n")
                    finally:
                        fcntl.flock(fd, fcntl.LOCK_UN)
                        os.close(fd)
                except Exception:
                    pass
        t = threading.Thread(target=_watchdog_loop, daemon=True)
        t.start()
