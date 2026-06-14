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
        runner.FALLBACK_TASK = task_dir / "task.md"
        with pytest.raises(SystemExit):
            runner.run(msg="test task")

        call_args = mock_terminal.run.call_args[0][0]
        assert "task.md" in call_args
        assert "--taskf" in call_args

        task_file = task_dir / "task.md"
        assert task_file.exists()
        assert "test task" in task_file.read_text()


def test_run_runner_task_mode_creates_task_file(tmp_path, mock_manager):
    from owrap.utils.paths import session_tasks_dir, session_task_output_dir

    sesh = mock_manager.session_id
    tasks_dir = session_tasks_dir(sesh)
    output_dir = session_task_output_dir(sesh)
    tasks_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    input_file = tmp_path / "input.md"
    input_file.write_text("task content")

    mock_manager.ensure_running.return_value = "http://localhost:4096"

    with patch("owrap.commands.run_cmd.Terminal") as mock_terminal_cls, \
         patch("owrap.commands.run_cmd._pool_active", return_value=False):
        mock_terminal = MagicMock()
        mock_terminal.run.return_value = {"returncode": 0, "stdout": ""}
        mock_terminal_cls.return_value = mock_terminal

        from owrap.commands.run_cmd import RunRunner

        runner = RunRunner(mock_manager)
        runner.INPUT_FILE = input_file

        with pytest.raises(SystemExit) as exc_info:
            runner.run(input_path=input_file)

        assert exc_info.value.code == 0

        task_name = "task_20260613_120000_000001.md"
        task_file = tasks_dir / task_name
        assert task_file.exists(), f"expected task file at {task_file}"
        assert "task content" in task_file.read_text()
        assert input_file.read_text() == ""

        log_path = output_dir / f"{task_name}.log"
        assert log_path.exists(), f"expected log at {log_path}"
        assert "task_" not in log_path.name[len("task_"):].split(".", 1)[0], \
            f"log filename must not double task_ prefix: {log_path.name}"


def test_run_runner_no_global_run_dir_side_effect(tmp_path, mock_manager):
    """Regression: _run_task must not create the real ~/.owrap/docs/run/ directory."""
    import shutil
    from owrap.commands.run_cmd import RunRunner
    from owrap.utils.paths import session_tasks_dir, session_task_output_dir

    sesh = mock_manager.session_id
    tasks_dir = session_tasks_dir(sesh)
    output_dir = session_task_output_dir(sesh)
    tasks_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    real_run = Path.home() / ".owrap" / "docs" / "run"
    if real_run.exists():
        shutil.rmtree(real_run)

    input_file = tmp_path / "input.md"
    input_file.write_text("test content")

    mock_manager.ensure_running.return_value = "http://localhost:4096"

    with patch("owrap.commands.run_cmd.Terminal") as mock_terminal_cls, \
         patch("owrap.commands.run_cmd._pool_active", return_value=False):
        mock_terminal = MagicMock()
        mock_terminal.run.return_value = {"returncode": 0, "stdout": ""}
        mock_terminal_cls.return_value = mock_terminal

        runner = RunRunner(mock_manager)
        runner.INPUT_FILE = input_file

        with pytest.raises(SystemExit):
            runner.run(input_path=input_file)

    assert not real_run.exists(), f"BUG: {real_run} was created by _run_task"


def test_run_runner_task_mode_empty_input(tmp_path, mock_manager):
    input_file = tmp_path / "input.md"
    input_file.write_text("")

    with patch("owrap.commands.run_cmd._pool_active", return_value=False):
        from owrap.commands.run_cmd import RunRunner

        runner = RunRunner(mock_manager)
        runner.INPUT_FILE = input_file

        with pytest.raises(SystemExit):
            runner.run(input_path=input_file)
