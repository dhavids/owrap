import json
import os
import threading
import time
from unittest.mock import patch

import pytest


class FakeProcess:
    def __init__(self, pid, final_rc):
        self.pid = pid
        self._final_rc = final_rc
        self._done = threading.Event()
        self._poll_count = 0

    def poll(self):
        self._poll_count += 1
        if self._done.is_set():
            return self._final_rc
        return None

    def wait(self):
        self._done.wait()
        return self._final_rc


class FakeTerminal:
    def __init__(self, chunks, final_rc=0, verbose=False):
        self._detached_stdout = []
        self._stdout_lock = threading.Lock()
        self._process = FakeProcess(pid=4242, final_rc=final_rc)
        self._chunks = chunks
        self._cmd = None
        self._verbose = verbose

    def run(self, cmd, detached=True, print_output=True):
        self._cmd = cmd
        t = threading.Thread(target=self._process_chunks, daemon=True)
        t.start()
        return {"pid": 4242, "process": self._process, "command": cmd, "detached": True, "success": None}

    def _process_chunks(self):
        for delay_s, text in self._chunks:
            time.sleep(delay_s)
            if text is not None:
                with self._stdout_lock:
                    self._detached_stdout.append(text)
        self._process._done.set()

    def is_running(self):
        return self._process.poll() is None

    def pop_clean_output(self):
        with self._stdout_lock:
            out = "".join(self._detached_stdout)
            self._detached_stdout.clear()
        return out

    @property
    def model(self):
        return None


class TestFallbackRun:
    def test_no_path_system_exit(self):
        from owrap.commands.fallback import FallbackRunner
        runner = FallbackRunner()
        with patch("owrap.commands.fallback.Terminal") as mock_cls:
            with pytest.raises(SystemExit) as exc_info:
                runner.run(None)
            assert exc_info.value.code == 1
            mock_cls.assert_not_called()

    def test_empty_path_system_exit(self):
        from owrap.commands.fallback import FallbackRunner
        runner = FallbackRunner()
        with patch("owrap.commands.fallback.Terminal") as mock_cls:
            with pytest.raises(SystemExit) as exc_info:
                runner.run("")
            assert exc_info.value.code == 1
            mock_cls.assert_not_called()

    def test_nonexistent_path_system_exit(self, tmp_path):
        from owrap.commands.fallback import FallbackRunner
        runner = FallbackRunner()
        missing = tmp_path / "missing_task.md"
        with patch("owrap.commands.fallback.Terminal") as mock_cls:
            with pytest.raises(SystemExit) as exc_info:
                runner.run(str(missing))
            assert exc_info.value.code == 1
            mock_cls.assert_not_called()

    def test_task_mode_success(self, tmp_path):
        from owrap.commands.fallback import FallbackRunner
        task_path = tmp_path / "task_do_stuff.md"
        task_path.write_text("## Do\n\nMy task title\n")

        output_dir = tmp_path / "task_fallback"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_log = output_dir / "output.log"
        run_log = output_dir / "log.md"
        status_file = output_dir / "status.json"

        runner = FallbackRunner()
        runner.TASK_OUTPUT = output_log
        runner.TASK_LOG = run_log
        runner.TASK_STATUS = status_file

        fake = FakeTerminal(chunks=[(0.01, "some output\n")], final_rc=0)
        with patch("owrap.commands.fallback.Terminal", return_value=fake):
            with pytest.raises(SystemExit) as exc_info:
                runner.run(str(task_path))
            assert exc_info.value.code == 0

        assert "--taskf" in fake._cmd
        assert str(task_path) in fake._cmd
        assert output_log.exists()
        content = output_log.read_text()
        assert "FALLBACK TASK START" in content
        assert "some output" in content
        assert run_log.exists()
        log_text = run_log.read_text()
        assert "rc=0" in log_text
        assert "My task title" in log_text

    def test_exec_mode_success(self, tmp_path):
        from owrap.commands.fallback import FallbackRunner
        plan_path = tmp_path / "plan_work.md"
        plan_path.write_text("# Exec task: p1 — my exec description\n")

        output_dir = tmp_path / "exec_fallback"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_log = output_dir / "output.log"
        run_log = output_dir / "log.md"
        status_file = output_dir / "status.json"

        runner = FallbackRunner()
        runner.EXEC_OUTPUT = output_log
        runner.EXEC_LOG = run_log
        runner.EXEC_STATUS = status_file

        fake = FakeTerminal(chunks=[(0.01, "exec output\n")], final_rc=0)
        with patch("owrap.commands.fallback.Terminal", return_value=fake):
            with pytest.raises(SystemExit) as exc_info:
                runner.run(str(plan_path))
            assert exc_info.value.code == 0

        assert "--execf" in fake._cmd
        assert str(plan_path) in fake._cmd
        assert output_log.exists()
        assert run_log.exists()
        log_text = run_log.read_text()
        assert "rc=0" in log_text
        assert "my exec description" in log_text

    def test_failing_run_exit_code_and_log(self, tmp_path):
        from owrap.commands.fallback import FallbackRunner
        plan_path = tmp_path / "plan_fail.md"
        plan_path.write_text("# Exec task: p2 — failing exec description\n")

        output_dir = tmp_path / "exec_fallback"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_log = output_dir / "output.log"
        run_log = output_dir / "log.md"
        status_file = output_dir / "status.json"

        runner = FallbackRunner()
        runner.EXEC_OUTPUT = output_log
        runner.EXEC_LOG = run_log
        runner.EXEC_STATUS = status_file

        fake = FakeTerminal(chunks=[(0.01, "error output\n")], final_rc=1)
        with patch("owrap.commands.fallback.Terminal", return_value=fake):
            with pytest.raises(SystemExit) as exc_info:
                runner.run(str(plan_path))
            assert exc_info.value.code == 1

        log_text = run_log.read_text()
        assert "rc=1" in log_text
        assert "failing exec description" in log_text

    def test_log_prepend_order(self, tmp_path):
        from owrap.commands.fallback import FallbackRunner
        plan_path = tmp_path / "plan_order.md"
        plan_path.write_text("# Exec task: p3 — order test desc\n")

        output_dir = tmp_path / "exec_fallback"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_log = output_dir / "output.log"
        run_log = output_dir / "log.md"
        run_log.write_text("existing entry\n")
        status_file = output_dir / "status.json"

        runner = FallbackRunner()
        runner.EXEC_OUTPUT = output_log
        runner.EXEC_LOG = run_log
        runner.EXEC_STATUS = status_file

        fake = FakeTerminal(chunks=[(0.01, "out\n")], final_rc=0)
        with patch("owrap.commands.fallback.Terminal", return_value=fake):
            with pytest.raises(SystemExit):
                runner.run(str(plan_path))

        lines = run_log.read_text().strip().split("\n")
        assert len(lines) >= 2
        assert lines[1] == "existing entry"
        assert "order test desc" in lines[0]

    def test_status_json_written_running_then_done(self, tmp_path, monkeypatch):
        from owrap.commands.fallback import FallbackRunner
        plan_path = tmp_path / "plan_status.md"
        plan_path.write_text("# Plan\nstatus test")

        output_dir = tmp_path / "exec_fallback"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_log = output_dir / "output.log"
        run_log = output_dir / "log.md"
        status_file = output_dir / "status.json"

        runner = FallbackRunner()
        monkeypatch.setattr(runner, "POLL_INTERVAL_S", 0.05)
        runner.EXEC_OUTPUT = output_log
        runner.EXEC_LOG = run_log
        runner.EXEC_STATUS = status_file

        fake = FakeTerminal(chunks=[(0.02, "hello\n")], final_rc=0)
        with patch("owrap.commands.fallback.Terminal", return_value=fake):
            with pytest.raises(SystemExit) as exc_info:
                runner.run(str(plan_path))
            assert exc_info.value.code == 0

        import json
        data = json.loads(status_file.read_text())
        assert data["status"] == "done"
        assert data["returncode"] == 0
        assert data["finished_at"] is not None
        assert data["fallback_pid"] == os.getpid()
        assert data["runner_pid"] == 4242

    def test_status_json_stalled_then_running(self, tmp_path, monkeypatch):
        from owrap.commands.fallback import FallbackRunner
        plan_path = tmp_path / "plan_stall.md"
        plan_path.write_text("# Plan\nstall test")

        output_dir = tmp_path / "exec_fallback"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_log = output_dir / "output.log"
        run_log = output_dir / "log.md"
        status_file = output_dir / "status.json"

        runner = FallbackRunner()
        monkeypatch.setattr(runner, "POLL_INTERVAL_S", 0.05)
        monkeypatch.setattr(runner, "STALL_THRESHOLD_S", 0.1)
        runner.EXEC_OUTPUT = output_log
        runner.EXEC_LOG = run_log
        runner.EXEC_STATUS = status_file

        statuses = []
        original = FallbackRunner._write_status

        def wrapper(self, sf, status):
            statuses.append(status["status"])
            return original(self, sf, status)

        fake = FakeTerminal(chunks=[(0.01, "a\n"), (0.3, None), (0.01, "b\n")], final_rc=0)
        with patch("owrap.commands.fallback.Terminal", return_value=fake), \
             patch.object(FallbackRunner, "_write_status", wrapper):
            with pytest.raises(SystemExit) as exc_info:
                runner.run(str(plan_path))
            assert exc_info.value.code == 0

        assert "running" in statuses
        assert "stalled" in statuses
        running_again_idx = None
        stalled_idx = None
        for i, s in enumerate(statuses):
            if s == "stalled":
                stalled_idx = i
            if stalled_idx is not None and s == "running" and i > stalled_idx:
                running_again_idx = i
                break
        assert stalled_idx is not None, f"Never stalled; statuses={statuses}"
        assert running_again_idx is not None, f"No 'running' after 'stalled'; statuses={statuses}"
        assert "done" in statuses

    def test_status_json_crashed(self, tmp_path):
        from owrap.commands.fallback import FallbackRunner
        plan_path = tmp_path / "plan_crash.md"
        plan_path.write_text("# Plan\ncrash test")

        output_dir = tmp_path / "exec_fallback"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_log = output_dir / "output.log"
        run_log = output_dir / "log.md"
        status_file = output_dir / "status.json"

        runner = FallbackRunner()
        runner.EXEC_OUTPUT = output_log
        runner.EXEC_LOG = run_log
        runner.EXEC_STATUS = status_file

        fake = FakeTerminal(chunks=[(0.01, "boom\n")], final_rc=1)
        with patch("owrap.commands.fallback.Terminal", return_value=fake):
            with pytest.raises(SystemExit) as exc_info:
                runner.run(str(plan_path))
            assert exc_info.value.code == 1

        import json
        data = json.loads(status_file.read_text())
        assert data["status"] == "crashed"
        assert data["returncode"] == 1


class TestFallbackStop:
    def test_tstop_no_status_file_exits_1(self, tmp_path, capsys, monkeypatch):
        from owrap.commands.fallback import FallbackRunner

        task_status = tmp_path / "f" / "task" / "status.json"
        task_log = tmp_path / "f" / "task" / "log.md"

        runner = FallbackRunner()
        monkeypatch.setattr(runner, "TASK_STATUS", task_status)
        monkeypatch.setattr(runner, "TASK_LOG", task_log)

        with pytest.raises(SystemExit) as exc_info:
            runner.run("tstop")
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "No task fallback status file found" in captured.err

    def test_tstop_stops_running_process(self, tmp_path, monkeypatch):
        import subprocess
        from owrap.commands.fallback import FallbackRunner

        task_status = tmp_path / "f" / "task" / "status.json"
        task_log = tmp_path / "f" / "task" / "log.md"
        task_status.parent.mkdir(parents=True, exist_ok=True)

        proc = subprocess.Popen(["sleep", "100"])
        pid = proc.pid
        monkeypatch.setattr(FallbackRunner, "TASK_STATUS", task_status)
        monkeypatch.setattr(FallbackRunner, "TASK_LOG", task_log)

        status_data = {
            "target": "/tmp/x.md",
            "mode": "task",
            "started_at": "2025-01-01T00:00:00",
            "finished_at": None,
            "runner_pid": pid,
            "status": "running",
            "returncode": None,
        }
        task_status.write_text(json.dumps(status_data))

        try:
            runner = FallbackRunner()
            runner.stop("task")

            proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=1)
            pytest.fail("Process was not SIGTERMed")
        except ProcessLookupError:
            pass

        updated = json.loads(task_status.read_text())
        assert updated["status"] == "stopped"
        assert updated["returncode"] is None
        assert updated["finished_at"] is not None

        assert task_log.exists()
        log_text = task_log.read_text()
        assert "stopped" in log_text or "(rc=stopped)" in log_text

    def test_tstop_done_status_exits_0_no_signal(self, tmp_path, capsys, monkeypatch):
        from owrap.commands.fallback import FallbackRunner

        task_status = tmp_path / "f" / "task" / "status.json"
        task_log = tmp_path / "f" / "task" / "log.md"
        task_status.parent.mkdir(parents=True, exist_ok=True)

        original_content = json.dumps({
            "target": "/tmp/x.md",
            "mode": "task",
            "started_at": "2025-01-01T00:00:00",
            "finished_at": "2025-01-01T00:05:00",
            "runner_pid": 99999,
            "status": "done",
            "returncode": 0,
        })
        task_status.write_text(original_content)

        monkeypatch.setattr(FallbackRunner, "TASK_STATUS", task_status)
        monkeypatch.setattr(FallbackRunner, "TASK_LOG", task_log)

        runner = FallbackRunner()
        with pytest.raises(SystemExit) as exc_info:
            runner.stop("task")
        assert exc_info.value.code == 0

        assert task_status.read_text() == original_content

    def test_estop_stops_running_process(self, tmp_path, monkeypatch):
        import subprocess
        from owrap.commands.fallback import FallbackRunner

        exec_status = tmp_path / "f" / "exec" / "status.json"
        exec_log = tmp_path / "f" / "exec" / "log.md"
        exec_status.parent.mkdir(parents=True, exist_ok=True)

        proc = subprocess.Popen(["sleep", "100"])
        pid = proc.pid
        monkeypatch.setattr(FallbackRunner, "EXEC_STATUS", exec_status)
        monkeypatch.setattr(FallbackRunner, "EXEC_LOG", exec_log)

        status_data = {
            "target": "/tmp/y.md",
            "mode": "exec",
            "started_at": "2025-01-01T00:00:00",
            "finished_at": None,
            "runner_pid": pid,
            "status": "running",
            "returncode": None,
        }
        exec_status.write_text(json.dumps(status_data))

        try:
            runner = FallbackRunner()
            runner.stop("exec")

            proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=1)
            pytest.fail("Process was not SIGTERMed")
        except ProcessLookupError:
            pass

        updated = json.loads(exec_status.read_text())
        assert updated["status"] == "stopped"
        assert updated["returncode"] is None

        assert exec_log.exists()
        log_text = exec_log.read_text()
        assert "stopped" in log_text or "(rc=stopped)" in log_text
