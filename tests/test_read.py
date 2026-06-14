from unittest.mock import MagicMock, patch
from pathlib import Path
import sys

import pytest


def test_oread_disabled_prints_message_help(tmp_path, capsys):
    """oread -h prints OREAD_DISABLED_MSG when oread is false."""
    with patch.object(sys, "argv", ["oread", "read", "-h"]), \
         patch("owrap.runner._read_config", return_value={"default_workspace": "test"}), \
         patch("owrap.runner.get_workspace_config", return_value={"oread": False}):
        with pytest.raises(SystemExit):
            from owrap.runner import main
            main()
    captured = capsys.readouterr()
    assert "oread is disabled" in captured.out


def test_oread_disabled_prints_message_file(tmp_path, capsys):
    """oread -f <file> prints OREAD_DISABLED_MSG when oread is false."""
    test_file = tmp_path / "test.txt"
    test_file.write_text("hello")
    with patch.object(sys, "argv", ["oread", "read", "-f", str(test_file)]), \
         patch("owrap.runner._read_config", return_value={"default_workspace": "test"}), \
         patch("owrap.runner.get_workspace_config", return_value={"oread": False}):
        with pytest.raises(SystemExit):
            from owrap.runner import main
            main()
    captured = capsys.readouterr()
    assert "oread is disabled" in captured.out


def test_oread_disabled_prints_message_grep(tmp_path, capsys):
    """oread -g <pattern> prints OREAD_DISABLED_MSG when oread is false."""
    with patch.object(sys, "argv", ["oread", "read", "-g", "pattern"]), \
         patch("owrap.runner._read_config", return_value={"default_workspace": "test"}), \
         patch("owrap.runner.get_workspace_config", return_value={"oread": False}):
        with pytest.raises(SystemExit):
            from owrap.runner import main
            main()
    captured = capsys.readouterr()
    assert "oread is disabled" in captured.out


def test_oread_enabled_does_not_print_message(tmp_path, capsys):
    """oread -f <file> does NOT print OREAD_DISABLED_MSG when oread is true."""
    test_file = tmp_path / "test.txt"
    test_file.write_text("hello")
    with patch.object(sys, "argv", ["oread", "read", "-f", str(test_file)]), \
         patch("owrap.runner._read_config", return_value={"default_workspace": "test"}), \
         patch("owrap.runner.get_workspace_config", return_value={"oread": True}), \
         patch("owrap.commands.read.Terminal") as mock_terminal_cls, \
         patch("owrap.commands.read._pool_active", return_value=False):
        mock_terminal = MagicMock()
        mock_terminal.run.return_value = {"returncode": 0, "stdout": ""}
        mock_terminal_cls.return_value = mock_terminal
        with pytest.raises(SystemExit):
            from owrap.runner import main
            main()
    captured = capsys.readouterr()
    assert "oread is disabled" not in captured.out


def test_read_runner_prompt_construction(mock_manager):
    mock_manager.ensure_running.return_value = "http://localhost:4096"

    with patch("owrap.commands.read.Terminal") as mock_terminal_cls, \
         patch("owrap.commands.read._pool_active", return_value=False):
        mock_terminal = MagicMock()
        mock_terminal.run.return_value = {"returncode": 0, "stdout": ""}
        mock_terminal_cls.return_value = mock_terminal

        from owrap.commands.read import ReadRunner

        runner = ReadRunner(mock_manager)
        with pytest.raises(SystemExit):
            runner.run("/some/file.txt", summarise=True)

        mock_terminal.run.assert_called_once()
        call_args = mock_terminal.run.call_args[0][0]
        assert "/some/file.txt" in call_args
        assert "summarise" in call_args.lower()


def test_read_runner_with_summarise(mock_manager):
    mock_manager.ensure_running.return_value = "http://localhost:4096"

    with patch("owrap.commands.read.Terminal") as mock_terminal_cls, \
         patch("owrap.commands.read._pool_active", return_value=False):
        mock_terminal = MagicMock()
        mock_terminal.run.return_value = {"returncode": 0, "stdout": ""}
        mock_terminal_cls.return_value = mock_terminal

        from owrap.commands.read import ReadRunner

        runner = ReadRunner(mock_manager)
        with pytest.raises(SystemExit):
            runner.run("/some/file.txt", summarise=True)

        call_args = mock_terminal.run.call_args[0][0]
        assert "summarise" in call_args.lower()


def test_read_runner_with_details(mock_manager):
    mock_manager.ensure_running.return_value = "http://localhost:4096"

    with patch("owrap.commands.read.Terminal") as mock_terminal_cls, \
         patch("owrap.commands.read._pool_active", return_value=False):
        mock_terminal = MagicMock()
        mock_terminal.run.return_value = {"returncode": 0, "stdout": ""}
        mock_terminal_cls.return_value = mock_terminal

        from owrap.commands.read import ReadRunner

        runner = ReadRunner(mock_manager)
        with pytest.raises(SystemExit):
            runner.run("/some/file.txt", details="specific function")

        call_args = mock_terminal.run.call_args[0][0]
        assert "specific function" in call_args


def test_read_runner_with_url(mock_manager):
    mock_manager.ensure_running.return_value = "http://localhost:4096"

    with patch("owrap.commands.read.Terminal") as mock_terminal_cls, \
         patch("owrap.commands.read._pool_active", return_value=False):
        mock_terminal = MagicMock()
        mock_terminal.run.return_value = {"returncode": 0, "stdout": ""}
        mock_terminal_cls.return_value = mock_terminal

        from owrap.commands.read import ReadRunner

        runner = ReadRunner(mock_manager)
        with pytest.raises(SystemExit):
            runner.run("/some/file.txt", summarise=True)

        call_args = mock_terminal.run.call_args[0][0]
        assert "--attach" in call_args
        assert "http://localhost:4096" in call_args


def test_read_runner_fallback_without_url(tmp_path, mock_manager):
    task_dir = tmp_path / "run"
    task_dir.mkdir()

    with patch("owrap.commands.read.Terminal") as mock_terminal_cls, \
         patch("owrap.commands.read._pool_active", return_value=False):
        mock_terminal = MagicMock()
        mock_terminal.run.return_value = {"returncode": 0, "stdout": ""}
        mock_terminal_cls.return_value = mock_terminal

        from owrap.commands.read import ReadRunner

        runner = ReadRunner(mock_manager)
        runner.TASKS_DIR = task_dir
        runner.FALLBACK_TASK = task_dir / "task.md"
        with pytest.raises(SystemExit):
            runner.run("/some/file.txt", summarise=True)

        call_args = mock_terminal.run.call_args[0][0]
        assert "task.md" in call_args
        assert "--task" in call_args
        assert "--fast" not in call_args

        task_file = task_dir / "task.md"
        assert task_file.exists()
        assert "/some/file.txt" in task_file.read_text()
