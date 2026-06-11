import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def test_run_runner_msg_validation_newlines(mock_manager):
    from owrap.commands.run_cmd import RunRunner

    runner = RunRunner(mock_manager)
    with pytest.raises(SystemExit):
        runner.run(msg="line1\nline2")


def test_run_runner_msg_validation_length(mock_manager):
    from owrap.commands.run_cmd import RunRunner

    runner = RunRunner(mock_manager)
    with pytest.raises(SystemExit):
        runner.run(msg="x" * 1025)


def test_run_runner_msg_mode_calls_opencode(mock_manager):
    mock_manager.ensure_running.return_value = "http://localhost:4096"

    with patch("owrap.commands.run_cmd.Terminal") as mock_terminal_cls, \
         patch("owrap.commands.run_cmd._pool_active", return_value=False):
        mock_terminal = MagicMock()
        mock_terminal.run.return_value = {"returncode": 0, "stdout": ""}
        mock_terminal_cls.return_value = mock_terminal

        from owrap.commands.run_cmd import RunRunner

        runner = RunRunner(mock_manager)
        with pytest.raises(SystemExit) as exc_info:
            runner.run(msg="test task")
        assert exc_info.value.code == 0

        mock_terminal.run.assert_called_once()
        call_args = mock_terminal.run.call_args[0][0]
        assert "--attach" in call_args
        assert "http://localhost:4096" in call_args
        assert "test task" in call_args


def test_run_runner_msg_mode_fallback_without_url(tmp_path, mock_manager):
    task_dir = tmp_path / "run"
    task_dir.mkdir()

    with patch("owrap.commands.run_cmd.Terminal") as mock_terminal_cls, \
         patch("owrap.commands.run_cmd._pool_active", return_value=False):
        mock_terminal = MagicMock()
        mock_terminal.run.return_value = {"returncode": 0, "stdout": ""}
        mock_terminal_cls.return_value = mock_terminal

        from owrap.commands.run_cmd import RunRunner

        runner = RunRunner(mock_manager)
        runner.TASKS_DIR = task_dir
        with pytest.raises(SystemExit):
            runner.run(msg="test task")

        call_args = mock_terminal.run.call_args[0][0]
        assert "task0.md" in call_args
        assert "--taskf" in call_args

        task_file = task_dir / "task0.md"
        assert task_file.exists()
        assert "test task" in task_file.read_text()


def test_run_runner_task_mode_creates_task_file(tmp_path, mock_manager):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    output_dir = run_dir / "output"
    output_dir.mkdir()
    input_file = run_dir / "input.md"
    input_file.write_text("task content")

    mock_manager.ensure_running.return_value = "http://localhost:4096"

    with patch("owrap.commands.run_cmd.Terminal") as mock_terminal_cls, \
         patch("owrap.commands.run_cmd._pool_active", return_value=False):
        mock_terminal = MagicMock()
        mock_terminal.run.return_value = {"returncode": 0, "stdout": ""}
        mock_terminal_cls.return_value = mock_terminal

        from owrap.commands.run_cmd import RunRunner

        runner = RunRunner(mock_manager)
        runner.TASKS_DIR = run_dir
        runner.OUTPUT_DIR = output_dir
        runner.INPUT_FILE = input_file

        with pytest.raises(SystemExit) as exc_info:
            runner.run(input_path=input_file)

        assert exc_info.value.code == 0

        task_file = run_dir / "task1.md"
        assert task_file.exists()
        assert "task content" in task_file.read_text()
        assert input_file.read_text() == ""


def test_run_runner_task_mode_empty_input(tmp_path, mock_manager):
    input_file = tmp_path / "input.md"
    input_file.write_text("")

    with patch("owrap.commands.run_cmd._pool_active", return_value=False):
        from owrap.commands.run_cmd import RunRunner

        runner = RunRunner(mock_manager)
        runner.INPUT_FILE = input_file

        with pytest.raises(SystemExit):
            runner.run(input_path=input_file)
