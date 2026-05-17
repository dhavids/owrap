import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def test_run_runner_msg_validation_newlines():
    from util.misc.opencode.run_cmd import RunRunner

    runner = RunRunner()
    with pytest.raises(SystemExit):
        runner.run(msg="line1\nline2")


def test_run_runner_msg_validation_length():
    from util.misc.opencode.run_cmd import RunRunner

    runner = RunRunner()
    with pytest.raises(SystemExit):
        runner.run(msg="x" * 513)


def test_run_runner_msg_mode_calls_opencode():
    with patch("util.misc.opencode.run_cmd.OpenCodeManager") as mock_manager_cls, \
         patch("util.misc.opencode.run_cmd.Terminal") as mock_terminal_cls:
        mock_manager = MagicMock()
        mock_manager.ensure_running.return_value = "http://localhost:4096"
        mock_manager_cls.return_value = mock_manager

        mock_terminal = MagicMock()
        mock_terminal_cls.return_value = mock_terminal

        from util.misc.opencode.run_cmd import RunRunner

        runner = RunRunner()
        runner.run(msg="test task")

        mock_terminal.run.assert_called_once()
        call_args = mock_terminal.run.call_args[0][0]
        assert "--task" in call_args
        assert "--do" in call_args
        assert "test task" in call_args


def test_run_runner_msg_mode_fallback_without_url(tmp_path):
    task_dir = tmp_path / "run"
    task_dir.mkdir()

    with patch("util.misc.opencode.run_cmd.OpenCodeManager") as mock_manager_cls, \
         patch("util.misc.opencode.run_cmd.Terminal") as mock_terminal_cls:
        mock_manager = MagicMock()
        mock_manager.ensure_running.return_value = None
        mock_manager_cls.return_value = mock_manager

        mock_terminal = MagicMock()
        mock_terminal_cls.return_value = mock_terminal

        from util.misc.opencode.run_cmd import RunRunner

        runner = RunRunner()
        runner.TASKS_DIR = task_dir
        runner.run(msg="test task")

        call_args = mock_terminal.run.call_args[0][0]
        assert "task0.md" in call_args
        assert "--task" in call_args

        task_file = task_dir / "task0.md"
        assert task_file.exists()
        assert "test task" in task_file.read_text()


def test_run_runner_task_mode_creates_task_file(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    output_dir = run_dir / "output"
    output_dir.mkdir()
    input_file = run_dir / "input.md"
    input_file.write_text("task content")

    with patch("util.misc.opencode.run_cmd.OpenCodeManager") as mock_manager_cls, \
         patch("util.misc.opencode.run_cmd.Terminal") as mock_terminal_cls:
        mock_manager = MagicMock()
        mock_manager.ensure_running.return_value = "http://localhost:4096"
        mock_manager.next_task_id.return_value = 1
        mock_manager._t_cmd_end = None
        mock_manager_cls.return_value = mock_manager

        mock_terminal = MagicMock()
        mock_terminal.run.return_value = {"returncode": 0, "stdout": ""}
        mock_terminal_cls.return_value = mock_terminal

        from util.misc.opencode.run_cmd import RunRunner

        runner = RunRunner()
        runner.TASKS_DIR = run_dir
        runner.OUTPUT_DIR = output_dir
        runner.INPUT_FILE = input_file

        with pytest.raises(SystemExit) as exc_info:
            runner.run(input_path=input_file)

        assert exc_info.value.code == 0

        task_file = run_dir / "task1.md"
        assert task_file.exists()
        assert task_file.read_text() == "task content"
        assert input_file.read_text() == ""


def test_run_runner_task_mode_empty_input(tmp_path):
    input_file = tmp_path / "input.md"
    input_file.write_text("")

    from util.misc.opencode.run_cmd import RunRunner

    runner = RunRunner()
    runner.INPUT_FILE = input_file

    with pytest.raises(SystemExit):
        runner.run(input_path=input_file)
