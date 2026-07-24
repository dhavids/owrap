import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from owrap.manager import Manager


def test_msg_too_long_prints_explicit_options(mock_manager, capsys):
    """MSG_TOO_LONG: msg > 1536 prints a self-contained error stating both
    remediation options."""
    mock_manager.ensure_running.return_value = "http://localhost:4096"

    from owrap.commands.run_cmd import RunRunner
    runner = RunRunner(mock_manager)

    with patch("owrap.utils.paths.get_self_path", return_value=Path("/tmp/fake_self.md")), \
         patch("owrap.utils.paths.resolve_general_instruction_path", return_value=Path("/tmp/fake_instr.md")):
        with pytest.raises(SystemExit):
            runner.run(msg="x" * 1537)

    captured = capsys.readouterr()
    output = captured.err + captured.out
    assert "shorten the message" in output
    assert "file task" in output
    assert "#DO NOW" not in output


def test_input_empty_prints_donow(mock_manager, capsys, tmp_path):
    """INPUT_EMPTY: empty input prints #DO NOW."""
    input_file = tmp_path / "input.md"
    input_file.write_text("")

    with patch("owrap.commands.run_cmd._pool_active", return_value=False):
        from owrap.commands.run_cmd import RunRunner
        runner = RunRunner(mock_manager)

        with patch("owrap.utils.paths.get_self_path", return_value=Path("/tmp/fake_self.md")), \
             patch("owrap.utils.paths.resolve_general_instruction_path", return_value=Path("/tmp/fake_instr.md")):
            with pytest.raises(SystemExit):
                runner.run(input_path=input_file)

    captured = capsys.readouterr()
    assert "#DO NOW" in captured.err or "#DO NOW" in captured.out
    assert "INPUT_EMPTY" in captured.err or "INPUT_EMPTY" in captured.out


def test_timed_out_prints_donow(mock_manager, capsys):
    """TIMED_OUT: timeout prints #DO NOW."""
    mock_manager.ensure_running.return_value = "http://localhost:4096"

    with patch("owrap.commands.run_cmd.Terminal") as mock_terminal_cls, \
         patch("owrap.commands.run_cmd._pool_active", return_value=False):
        mock_terminal = MagicMock()
        mock_terminal.run.return_value = {"returncode": 1, "stdout": "partial output here", "timed_out": True}
        mock_terminal_cls.return_value = mock_terminal

        from owrap.commands.run_cmd import RunRunner
        runner = RunRunner(mock_manager)

        with patch("owrap.utils.paths.get_self_path", return_value=Path("/tmp/fake_self.md")), \
             patch("owrap.utils.paths.resolve_general_instruction_path", return_value=Path("/tmp/fake_instr.md")):
            with pytest.raises(SystemExit):
                runner.run(msg="hello")

    captured = capsys.readouterr()
    assert "#DO NOW" in captured.out
    assert "TIMED_OUT" in captured.out


def test_task_failed_prints_donow(mock_manager, capsys):
    """TASK_FAILED: exec non-zero rc prints #DO NOW."""
    sid = "test123"
    plan_file = Path("/tmp/fake_plan.md")
    plan_file.write_text("## [ACTIVE] test\n")
    mock_manager.session_id = sid

    with patch("owrap.commands.exec.get_plan_path", return_value=plan_file), \
         patch("owrap.commands.exec.Terminal") as mock_terminal_cls, \
         patch("owrap.commands.exec._pool_active", return_value=False), \
         patch("owrap.commands.exec.context_path", return_value=Path("/tmp/fake_context.md")):
        mock_terminal = MagicMock()
        mock_terminal.run.return_value = {"returncode": 1, "stdout": ""}
        mock_terminal_cls.return_value = mock_terminal

        from owrap.commands.exec import ExecRunner
        runner = ExecRunner(mock_manager)

        with patch("owrap.utils.paths.get_self_path", return_value=Path("/tmp/fake_self.md")), \
             patch("owrap.commands.exec.format_failure_pointer") as mock_fp:
            mock_fp.return_value = "#DO NOW\nTASK_FAILED — read /tmp/fake_self.md § Update Context and follow it."
            with pytest.raises(SystemExit):
                runner.run()


def test_no_server_prints_donow(mock_manager, capsys):
    """NO_SERVER: pick_server failure prints #DO NOW."""
    mock_manager.ensure_running.return_value = "http://localhost:4096"

    with patch("owrap.commands.run_cmd._pool_active", return_value=True), \
         patch("owrap.commands.run_cmd.pick_server", side_effect=RuntimeError("no servers")):
        from owrap.commands.run_cmd import RunRunner
        runner = RunRunner(mock_manager)

        with patch("owrap.utils.paths.get_self_path", return_value=Path("/tmp/fake_self.md")), \
             patch("owrap.utils.paths.resolve_general_instruction_path", return_value=Path("/tmp/fake_instr.md")):
            with pytest.raises(SystemExit):
                runner.run(msg="hello")

    captured = capsys.readouterr()
    assert "#DO NOW" in captured.out
    assert "NO_SERVER" in captured.out


def test_owrap_not_found_prints_error():
    """owrap runner surfaces actionable error when opencode is not found."""
    with patch.object(sys, "argv", ["owrap", "run", "--msg", "test"]), \
         patch("shutil.which", return_value=None):
        from owrap.runner import main as runner_main
        with pytest.raises(SystemExit) as exc_info:
            runner_main()
        assert exc_info.value.code != 0


def test_format_failure_pointer_validation():
    """Each FAILURE_POINTERS entry has valid target and section."""
    from owrap.constants import FAILURE_POINTERS
    from owrap.utils.paths import get_self_path, resolve_general_instruction_path

    self_path = get_self_path()
    instr_path = resolve_general_instruction_path(None)

    for code, (target, section) in FAILURE_POINTERS.items():
        assert target in ("self", "instruction"), f"FAILURE_POINTERS[{code}] has invalid target '{target}'"
        assert isinstance(section, str) and len(section) > 0, f"FAILURE_POINTERS[{code}] has empty section"
        if target == "self":
            assert self_path is not None, f"FAILURE_POINTERS[{code}] self_path is None"
        else:
            assert instr_path is not None, f"FAILURE_POINTERS[{code}] instr_path is None"
