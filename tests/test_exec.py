from unittest.mock import MagicMock, patch

import pytest


def test_exec_runner_calls_opencode_with_exec(tmp_path, mock_manager):
    log_dir = tmp_path / "exec" / "output"
    log_dir.mkdir(parents=True)
    log_file = log_dir / "exec_output.log"

    with patch("owrap.commands.exec.Terminal") as mock_terminal_cls:
        mock_terminal = MagicMock()
        mock_terminal.run.return_value = {"returncode": 0, "stdout": "output\n"}
        mock_terminal_cls.return_value = mock_terminal

        from owrap.commands.exec import ExecRunner

        runner = ExecRunner(mock_manager)
        runner.LOG_DIR = log_dir
        runner.LOG_FILE = log_file

        with pytest.raises(SystemExit) as exc_info:
            runner.run(disablewd=True)

        assert exc_info.value.code == 0


def test_exec_runner_with_url(tmp_path, mock_manager):
    log_dir = tmp_path / "exec" / "output"
    log_dir.mkdir(parents=True)
    log_file = log_dir / "exec_output.log"

    mock_manager.ensure_running.return_value = "http://localhost:4096"

    with patch("owrap.commands.exec.Terminal") as mock_terminal_cls, \
         patch("owrap.commands.exec._pool_active", return_value=False):
        mock_terminal = MagicMock()
        mock_terminal.run.return_value = {"returncode": 0, "stdout": ""}
        mock_terminal_cls.return_value = mock_terminal

        from owrap.commands.exec import ExecRunner

        runner = ExecRunner(mock_manager)
        runner.LOG_DIR = log_dir
        runner.LOG_FILE = log_file

        with pytest.raises(SystemExit):
            runner.run()

        call_args = mock_terminal.run.call_args[0][0]
        assert "--attach" in call_args


def test_exec_runner_creates_log_file(tmp_path, mock_manager):
    log_dir = tmp_path / "exec" / "output"
    log_dir.mkdir(parents=True)
    log_file = log_dir / f"exec_output_{mock_manager.session_id}.log"

    with patch("owrap.commands.exec.Terminal") as mock_terminal_cls, \
         patch("owrap.commands.exec.session_exec_output_path", return_value=log_file), \
         patch("owrap.commands.exec._pool_active", return_value=False):
        mock_terminal = MagicMock()
        mock_terminal.run.return_value = {"returncode": 0, "stdout": "line\n"}
        mock_terminal_cls.return_value = mock_terminal

        from owrap.commands.exec import ExecRunner

        runner = ExecRunner(mock_manager)
        runner.LOG_DIR = log_dir
        runner.LOG_FILE = log_file

        with pytest.raises(SystemExit):
            runner.run()

        assert mock_terminal.run.called


def test_exec_runner_locked_log_file_fallback(tmp_path, mock_manager):
    log_dir = tmp_path / "exec" / "output"
    log_dir.mkdir(parents=True)
    log_file = log_dir / f"exec_output_{mock_manager.session_id}.log"
    log_file.touch()

    with patch("owrap.commands.exec.Terminal") as mock_terminal_cls, \
          patch("owrap.commands.exec.session_exec_output_path", return_value=log_file), \
          patch("owrap.commands.exec._pool_active", return_value=False), \
          patch.object(type(log_file), "unlink", side_effect=OSError("file locked")):
        mock_terminal = MagicMock()
        mock_terminal.run.return_value = {"returncode": 0, "stdout": "line\n"}
        mock_terminal_cls.return_value = mock_terminal

        from owrap.commands.exec import ExecRunner

        runner = ExecRunner(mock_manager)
        runner.LOG_DIR = log_dir
        runner.LOG_FILE = log_file

        with pytest.raises(SystemExit):
            runner.run()

        assert mock_terminal.run.called
