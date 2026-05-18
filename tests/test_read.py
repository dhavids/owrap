from unittest.mock import MagicMock, patch
from pathlib import Path

import pytest


def test_read_runner_prompt_construction():
    with patch("owrap.commands.read.OpenCodeManager") as mock_manager_cls, \
         patch("owrap.commands.read.Terminal") as mock_terminal_cls:
        mock_manager = MagicMock()
        mock_manager.ensure_running.return_value = "http://localhost:4096"
        mock_manager_cls.return_value = mock_manager

        mock_terminal = MagicMock()
        mock_terminal_cls.return_value = mock_terminal

        from owrap.commands.read import ReadRunner

        runner = ReadRunner()
        runner.run("/some/file.txt")

        mock_terminal.run.assert_called_once()
        call_args = mock_terminal.run.call_args[0][0]
        assert "/some/file.txt" in call_args
        assert "summarise" not in call_args.lower()


def test_read_runner_with_summarise():
    with patch("owrap.commands.read.OpenCodeManager") as mock_manager_cls, \
         patch("owrap.commands.read.Terminal") as mock_terminal_cls:
        mock_manager = MagicMock()
        mock_manager.ensure_running.return_value = "http://localhost:4096"
        mock_manager_cls.return_value = mock_manager

        mock_terminal = MagicMock()
        mock_terminal_cls.return_value = mock_terminal

        from owrap.commands.read import ReadRunner

        runner = ReadRunner()
        runner.run("/some/file.txt", summarise=True)

        call_args = mock_terminal.run.call_args[0][0]
        assert "summarise" in call_args.lower()


def test_read_runner_with_details():
    with patch("owrap.commands.read.OpenCodeManager") as mock_manager_cls, \
         patch("owrap.commands.read.Terminal") as mock_terminal_cls:
        mock_manager = MagicMock()
        mock_manager.ensure_running.return_value = "http://localhost:4096"
        mock_manager_cls.return_value = mock_manager

        mock_terminal = MagicMock()
        mock_terminal_cls.return_value = mock_terminal

        from owrap.commands.read import ReadRunner

        runner = ReadRunner()
        runner.run("/some/file.txt", details="specific function")

        call_args = mock_terminal.run.call_args[0][0]
        assert "specific function" in call_args


def test_read_runner_with_url():
    with patch("owrap.commands.read.OpenCodeManager") as mock_manager_cls, \
         patch("owrap.commands.read.Terminal") as mock_terminal_cls:
        mock_manager = MagicMock()
        mock_manager.ensure_running.return_value = "http://localhost:4096"
        mock_manager_cls.return_value = mock_manager

        mock_terminal = MagicMock()
        mock_terminal_cls.return_value = mock_terminal

        from owrap.commands.read import ReadRunner

        runner = ReadRunner()
        runner.run("/some/file.txt")

        call_args = mock_terminal.run.call_args[0][0]
        assert "--attach" in call_args
        assert "http://localhost:4096" in call_args


def test_read_runner_fallback_without_url(tmp_path):
    task_dir = tmp_path / "run"
    task_dir.mkdir()

    with patch("owrap.commands.read.OpenCodeManager") as mock_manager_cls, \
         patch("owrap.commands.read.Terminal") as mock_terminal_cls:
        mock_manager = MagicMock()
        mock_manager.ensure_running.return_value = None
        mock_manager_cls.return_value = mock_manager

        mock_terminal = MagicMock()
        mock_terminal_cls.return_value = mock_terminal

        from owrap.commands.read import ReadRunner

        runner = ReadRunner()
        runner.TASKS_DIR = task_dir
        runner.run("/some/file.txt")

        call_args = mock_terminal.run.call_args[0][0]
        assert "task0.md" in call_args
        assert "--task" in call_args
        assert "--fast" not in call_args

        task_file = task_dir / "task0.md"
        assert task_file.exists()
        assert "/some/file.txt" in task_file.read_text()
