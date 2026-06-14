import os
import signal
import subprocess
import threading
from pathlib import Path
from typing import Optional

from .output_parser import OutputParser


_MUTE_LINE_PREFIXES = (
    "Warning: OPENCODE_SERVER_PASSWORD is not set",
    "opencode server listening on",
)


class Terminal:
    """Subprocess wrapper with PTY-backed detached execution and stdout streaming.

    Keeps only the core subprocess management: Popen, stdout stream, tee to file.
    """

    def __init__(
        self,
        interactive_shell: bool = False,
        stop_on_error: bool = False,
        name: str = "Terminal",
        verbose: bool = True,
        signals: str = "all",
        send_sigint: bool = False,
    ):
        self.interactive_shell = interactive_shell
        self.stop_on_error = stop_on_error
        self.verbose = verbose
        self.name = name
        self.signals = signals
        self.send_sigint = send_sigint

        self._process = None
        self.cmd = ""
        self._pty_master_fd = None
        self._detached_stdout: list[str] = []
        self._detached_stdout_clean: list[str] = []
        self._output_parser = OutputParser()
        self._detached_stderr: list[str] = []
        self._stdout_lock = threading.Lock()
        self._signal_handlers_registered = False
        self._original_handlers: dict[int, object] = {}
        self._handling_signal = False

    def _get_signals_to_register(self, signals=None):
        sig_config = signals if signals is not None else self.signals
        if sig_config in ("all", True):
            return [signal.SIGINT, signal.SIGTERM]
        elif sig_config in ("none", False, None):
            return []
        elif sig_config in ("sigterm", "SIGTERM"):
            return [signal.SIGTERM]
        elif sig_config in ("sigint", "SIGINT"):
            return [signal.SIGINT]
        elif isinstance(sig_config, (list, tuple)):
            return list(sig_config)
        return [signal.SIGINT, signal.SIGTERM]

    def register_signal_handlers(self, signals=None):
        if self._signal_handlers_registered:
            return
        signals_to_register = self._get_signals_to_register(signals)
        if not signals_to_register:
            return
        self._original_handlers = {}
        for sig in signals_to_register:
            self._original_handlers[sig] = signal.signal(sig, self._signal_handler)
        self._signal_handlers_registered = True

    def unregister_signal_handlers(self):
        if not self._signal_handlers_registered:
            return
        for sig, handler in self._original_handlers.items():
            signal.signal(sig, handler)
        self._signal_handlers_registered = False
        self._original_handlers = {}

    def _signal_handler(self, signum, frame):
        if self._handling_signal:
            return
        self._handling_signal = True
        if self.verbose:
            print(f"[{self.name}] Caught signal {signum}")
        if self.send_sigint and signum == signal.SIGINT and self.is_running():
            if self.send_stdin("\x03"):
                import time
                time.sleep(1.0)
        self.terminate_process()
        original = self._original_handlers.get(signum)
        if original and callable(original) and original not in (signal.SIG_IGN, signal.SIG_DFL):
            original(signum, frame)
        elif original == signal.SIG_DFL:
            signal.signal(signum, signal.SIG_DFL)
            os.kill(os.getpid(), signum)

    def is_running(self):
        return self._process is not None and self._process.poll() is None

    def terminate_process(self, timeout=3):
        if self._process is None:
            return False
        proc = self._process
        pid = proc.pid
        if self.verbose:
            print(f"[{self.name}] Terminating process tree rooted at PID {pid}")
        try:
            try:
                pgid = os.getpgid(pid)
                os.killpg(pgid, signal.SIGTERM)
            except Exception:
                proc.terminate()
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(pgid, signal.SIGKILL)
                except Exception:
                    proc.kill()
                proc.wait(timeout=1)
        finally:
            self._process = None
            return True

    def run(
        self,
        command,
        *,
        stdin=None,
        capture_output=False,
        print_output=True,
        silent=False,
        detached=False,
        timeout=None,
        register_signals=True,
        signals=None,
        tee_file=None,
        cwd=None,
    ):
        if silent:
            print_output = False
        if register_signals:
            self.register_signal_handlers(signals=signals)
        self.cmd = command
        try:
            if detached:
                return self._run_detached(command, stdin, print_output)
            elif self.interactive_shell:
                return self._run_interactive(command, stdin, capture_output, print_output, silent, timeout)
            else:
                return self._run_standard(command, stdin, capture_output, print_output, silent, timeout, tee_file, cwd=cwd)
        finally:
            if register_signals and not detached:
                self.unregister_signal_handlers()

    def send_stdin(self, data: str) -> bool:
        if not self.is_running():
            return False
        try:
            if self._pty_master_fd is not None:
                os.write(self._pty_master_fd, data.encode())
                return True
            elif self._process.stdin:
                self._process.stdin.write(data)
                self._process.stdin.flush()
                return True
        except Exception:
            return False
        return False

    def _run_detached(self, command, stdin, print_output):
        import pty
        if self.verbose:
            print(f"Running (detached): {command}")
        master_fd, slave_fd = pty.openpty()
        self._process = subprocess.Popen(
            command,
            shell=True,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            text=True,
            preexec_fn=os.setsid,
            close_fds=True,
        )
        os.close(slave_fd)
        self._pty_master_fd = master_fd
        with self._stdout_lock:
            self._detached_stdout.clear()
            self._detached_stdout_clean.clear()
            self._output_parser = OutputParser()

        def pty_reader():
            while True:
                try:
                    data = os.read(master_fd, 1024)
                    if not data:
                        break
                    text = data.decode(errors="ignore")
                    clean = self._output_parser.feed(text)
                    with self._stdout_lock:
                        self._detached_stdout.append(text)
                        self._detached_stdout_clean.append(clean)
                    if print_output:
                        print(clean, end="")
                except OSError:
                    break
            tail = self._output_parser.flush()
            if tail:
                with self._stdout_lock:
                    self._detached_stdout_clean.append(tail)
                if print_output:
                    print(tail, end="")

        threading.Thread(target=pty_reader, daemon=True).start()
        if isinstance(stdin, str):
            os.write(master_fd, stdin.encode())
        return {
            "pid": self._process.pid,
            "process": self._process,
            "command": command,
            "detached": True,
            "success": None,
        }

    def _run_standard(self, command, stdin, capture_output, print_output, silent, timeout, tee_file=None, cwd=None):
        import time
        if self.verbose and not silent:
            print(f"Running: {command}")
        use_stdin_pipe = isinstance(stdin, str) or self.send_sigint
        proc = subprocess.Popen(
            command,
            shell=True,
            text=True,
            stdin=subprocess.PIPE if use_stdin_pipe else stdin,
            stdout=subprocess.PIPE if (capture_output or print_output) else None,
            stderr=subprocess.PIPE if (capture_output or print_output) else None,
            cwd=cwd,
        )
        self._process = proc
        if isinstance(stdin, str):
            proc.stdin.write(stdin)
            proc.stdin.close()
        if print_output and capture_output and not silent:
            stdout_lines = []
            stderr_lines = []
            self._partial_stdout = ""
            parser = OutputParser()
            import select
            import fcntl
            if proc.stdout:
                flags = fcntl.fcntl(proc.stdout, fcntl.F_GETFL)
                fcntl.fcntl(proc.stdout, fcntl.F_SETFL, flags | os.O_NONBLOCK)
            if proc.stderr:
                flags = fcntl.fcntl(proc.stderr, fcntl.F_GETFL)
                fcntl.fcntl(proc.stderr, fcntl.F_SETFL, flags | os.O_NONBLOCK)
            deadline = (time.time() + timeout) if timeout else None
            timed_out = False
            while proc.poll() is None:
                if deadline:
                    remaining = deadline - time.time()
                    if remaining <= 0:
                        timed_out = True
                        break
                    wait = min(0.1, remaining)
                else:
                    wait = 0.1
                readable, _, _ = select.select([proc.stdout, proc.stderr], [], [], wait)
                for stream in readable:
                    if stream == proc.stdout:
                        line = stream.readline()
                        if line:
                            stdout_lines.append(line)
                            self._partial_stdout += line
                            clean = parser.feed(line)
                            if not any(line.startswith(p) for p in _MUTE_LINE_PREFIXES):
                                print(clean, end="", flush=True)
                            if tee_file:
                                tee_file.write(clean)
                                tee_file.flush()
                    elif stream == proc.stderr:
                        line = stream.readline()
                        if line:
                            stderr_lines.append(line)
                            clean = parser.feed(line)
                            if not any(line.startswith(p) for p in _MUTE_LINE_PREFIXES):
                                print(clean, end="", flush=True)
                            if tee_file:
                                tee_file.write(clean)
                                tee_file.flush()
            if timed_out:
                tail = parser.flush()
                if tail:
                    print(tail, end="", flush=True)
                    if tee_file:
                        tee_file.write(tail)
                        tee_file.flush()
                self.terminate_process(timeout=2)
                self._process = None
                stdout = "".join(stdout_lines)
                stderr = "".join(stderr_lines)
                return {
                    "returncode": -1,
                    "stdout": stdout if capture_output else None,
                    "stderr": stderr if capture_output else None,
                    "success": False,
                    "timed_out": True,
                    "command": command,
                }
            try:
                remaining_stdout = proc.stdout.read()
            except TypeError:
                remaining_stdout = ""
            if remaining_stdout:
                stdout_lines.append(remaining_stdout)
                clean = parser.feed(remaining_stdout)
                print(clean, end="", flush=True)
                if tee_file:
                    tee_file.write(clean)
                    tee_file.flush()
            try:
                remaining_stderr = proc.stderr.read()
            except TypeError:
                remaining_stderr = ""
            if remaining_stderr:
                stderr_lines.append(remaining_stderr)
                clean = parser.feed(remaining_stderr)
                if clean:
                    print(clean, end="", flush=True)
                if tee_file:
                    tee_file.write(clean)
                    tee_file.flush()
            tail = parser.flush()
            if tail:
                print(tail, end="", flush=True)
                if tee_file:
                    tee_file.write(tail)
                    tee_file.flush()
            stdout = "".join(stdout_lines)
            stderr = "".join(stderr_lines)
        else:
            stdout, stderr = proc.communicate(timeout=timeout)
            if print_output and stdout and not silent:
                print(stdout, flush=True)
            if stderr and not silent:
                print(stderr, flush=True)
        self._process = None
        return {
            "returncode": proc.returncode,
            "stdout": stdout if capture_output else None,
            "stderr": stderr if capture_output else None,
            "success": proc.returncode == 0,
            "command": command,
        }

    def _run_interactive(self, command, stdin, capture_output, print_output, silent, timeout):
        full_cmd = f"bash -i -c 'set +m; {command}'"
        if self.verbose and not silent:
            print(f"Running (interactive): {command}")
        self._process = subprocess.Popen(
            full_cmd,
            shell=True,
            text=True,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE if capture_output else None,
            stderr=subprocess.PIPE if capture_output else None,
            preexec_fn=os.setsid,
        )
        stdout, stderr = self._process.communicate(
            input=stdin if isinstance(stdin, str) else None,
            timeout=timeout,
        )
        rc = self._process.returncode
        self._process = None
        return {
            "returncode": rc,
            "stdout": stdout if capture_output else None,
            "stderr": stderr if capture_output else None,
            "success": rc == 0,
            "command": command,
        }

    def get_output(self):
        if self._process is None:
            return {"stdout": None, "stderr": None, "returncode": None, "running": False}
        running = self._process.poll() is None
        with self._stdout_lock:
            stdout = "".join(self._detached_stdout)
        return {
            "stdout": stdout,
            "stderr": None,
            "returncode": self._process.returncode,
            "running": running,
            "command": self.cmd,
        }

    def pop_output(self) -> str:
        with self._stdout_lock:
            out = "".join(self._detached_stdout)
            self._detached_stdout.clear()
        return out

    def pop_clean_output(self) -> str:
        with self._stdout_lock:
            out = "".join(self._detached_stdout_clean)
            self._detached_stdout_clean.clear()
        return out

    @property
    def model(self) -> Optional[str]:
        return self._output_parser.model

    def close(self):
        self.terminate_process()
        self.unregister_signal_handlers()

    def __enter__(self):
        self.register_signal_handlers()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def __del__(self):
        self.close()
