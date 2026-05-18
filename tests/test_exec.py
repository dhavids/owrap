from unittest.mock import MagicMock, patch

import pytest


def test_exec_runner_calls_opencode_with_exec(tmp_path):
    log_dir = tmp_path / "exec" / "output"
    log_dir.mkdir(parents=True)
    log_file = log_dir / "exec_output.log"

    with patch("owrap.commands.exec.OpenCodeManager") as mock_manager_cls, \
         patch("owrap.commands.exec.Terminal") as mock_terminal_cls:
        mock_manager = MagicMock()
        mock_manager.ensure_running.return_value = None
        mock_manager._t_cmd_end = None
        mock_manager_cls.return_value = mock_manager

        mock_terminal = MagicMock()
        mock_terminal.run.return_value = {"returncode": 0, "stdout": "output\n"}
        mock_terminal_cls.return_value = mock_terminal

        from owrap.commands.exec import ExecRunner

        runner = ExecRunner()
        runner.LOG_DIR = log_dir
        runner.LOG_FILE = log_file

        with pytest.raises(SystemExit) as exc_info:
            runner.run()

        assert exc_info.value.code == 0


def test_exec_runner_with_url(tmp_path):
    log_dir = tmp_path / "exec" / "output"
    log_dir.mkdir(parents=True)
    log_file = log_dir / "exec_output.log"

    with patch("owrap.commands.exec.OpenCodeManager") as mock_manager_cls, \
         patch("owrap.commands.exec.Terminal") as mock_terminal_cls:
        mock_manager = MagicMock()
        mock_manager.ensure_running.return_value = "http://localhost:4096"
        mock_manager._t_cmd_end = None
        mock_manager_cls.return_value = mock_manager

        mock_terminal = MagicMock()
        mock_terminal.run.return_value = {"returncode": 0, "stdout": ""}
        mock_terminal_cls.return_value = mock_terminal

        from owrap.commands.exec import ExecRunner

        runner = ExecRunner()
        runner.LOG_DIR = log_dir
        runner.LOG_FILE = log_file

        with pytest.raises(SystemExit):
            runner.run()

        call_args = mock_terminal.run.call_args[0][0]
        assert "--attach" in call_args
        assert "http://localhost:4096" in call_args


def test_exec_runner_creates_log_file(tmp_path):
    log_dir = tmp_path / "exec" / "output"
    log_dir.mkdir(parents=True)
    log_file = log_dir / "exec_output.log"

    with patch("owrap.commands.exec.OpenCodeManager") as mock_manager_cls, \
         patch("owrap.commands.exec.Terminal") as mock_terminal_cls:
        mock_manager = MagicMock()
        mock_manager.ensure_running.return_value = None
        mock_manager._t_cmd_end = None
        mock_manager_cls.return_value = mock_manager

        mock_terminal = MagicMock()
        mock_terminal.run.return_value = {"returncode": 0, "stdout": "line\n"}
        mock_terminal_cls.return_value = mock_terminal

        from owrap.commands.exec import ExecRunner

        runner = ExecRunner()
        runner.LOG_DIR = log_dir
        runner.LOG_FILE = log_file

        with pytest.raises(SystemExit):
            runner.run()

        assert log_file.exists()
        content = log_file.read_text()
        assert "EXEC SESSION START" in content


def test_exec_runner_locked_log_file_fallback(tmp_path):
    log_dir = tmp_path / "exec" / "output"
    log_dir.mkdir(parents=True)
    log_file = log_dir / "exec_output.log"
    log_file.touch()

    with patch("owrap.commands.exec.OpenCodeManager") as mock_manager_cls, \
          patch("owrap.commands.exec.Terminal") as mock_terminal_cls, \
          patch.object(type(log_file), "unlink", side_effect=OSError("file locked")):
        mock_manager = MagicMock()
        mock_manager.ensure_running.return_value = None
        mock_manager._t_cmd_end = None
        mock_manager_cls.return_value = mock_manager

        mock_terminal = MagicMock()
        mock_terminal.run.return_value = {"returncode": 0, "stdout": "line\n"}
        mock_terminal_cls.return_value = mock_terminal

        from owrap.commands.exec import ExecRunner

        runner = ExecRunner()
        runner.LOG_DIR = log_dir
        runner.LOG_FILE = log_file

        with pytest.raises(SystemExit):
            runner.run()

        assert log_file.exists()
        timestamped_logs = list(log_dir.glob("exec_output_*.log"))
        assert len(timestamped_logs) == 1
