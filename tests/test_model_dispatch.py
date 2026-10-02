from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from owrap.utils.paths import _read_config

# Read the live config so model-name assertions stay in sync with ~/.owrap/configs.
_LIVE_CONFIG = _read_config()
EXPECTED_RUNNER_MODEL = _LIVE_CONFIG.get("runner_model", "opencode-go/qwen3.6-plus")


class TestGetDispatchModel:
    @pytest.mark.parametrize("config,override,default_to_fast,expected", [
        ({"runner_model": "a"}, "b", False, "b"),
        ({"runner_model": "a"}, None, False, "a"),
        ({"fast_model": "c"}, None, True, "c"),
        ({"fast_model": "c"}, None, False, None),
        ({}, None, False, None),
    ], ids=[
        "override_wins", "runner_model_next",
        "fast_model_when_allowed", "fast_model_ignored_when_not_allowed",
        "none_when_empty",
    ])
    def test_get_dispatch_model(self, config, override, default_to_fast, expected):
        from owrap.utils.paths import get_dispatch_model
        assert get_dispatch_model(
            config, override=override, default_to_fast=default_to_fast,
        ) == expected


def test_run_msg_passes_cli_model(mock_manager):
    mock_manager.ensure_running.return_value = "http://localhost:4096"

    with patch("owrap.commands.run_cmd.Terminal") as mock_terminal_cls, \
         patch("owrap.commands.run_cmd._pool_active", return_value=False), \
         patch("owrap.commands.run_cmd.get_workspace_path", return_value=Path("/tmp/ws")), \
         patch("owrap.utils.paths.get_self_path", return_value=Path("/tmp/fake_self.md")), \
         patch("owrap.utils.paths.resolve_general_instruction_path", return_value=Path("/tmp/fake_instr.md")):
        mock_terminal = MagicMock()
        mock_terminal.run.return_value = {"returncode": 0, "stdout": ""}
        mock_terminal_cls.return_value = mock_terminal

        from owrap.commands.run_cmd import RunRunner
        runner = RunRunner(mock_manager, model="opencode/test-override")
        with pytest.raises(SystemExit):
            runner.run(msg="hello")

    cmd = mock_terminal.run.call_args[0][0]
    assert "-m opencode/test-override" in cmd
    assert "--executor" in cmd


def test_run_msg_passes_fast_model_from_config(mock_manager):
    mock_manager.ensure_running.return_value = "http://localhost:4096"

    with patch("owrap.commands.run_cmd.Terminal") as mock_terminal_cls, \
         patch("owrap.commands.run_cmd._pool_active", return_value=False), \
         patch("owrap.commands.run_cmd.get_workspace_path", return_value=Path("/tmp/ws")), \
         patch("owrap.utils.paths.get_self_path", return_value=Path("/tmp/fake_self.md")), \
         patch("owrap.utils.paths.resolve_general_instruction_path", return_value=Path("/tmp/fake_instr.md")), \
         patch("owrap.commands.run_cmd._read_config", return_value={"fast_model": "opencode/fast"}):
        mock_terminal = MagicMock()
        mock_terminal.run.return_value = {"returncode": 0, "stdout": ""}
        mock_terminal_cls.return_value = mock_terminal

        from owrap.commands.run_cmd import RunRunner
        runner = RunRunner(mock_manager)
        with pytest.raises(SystemExit):
            runner.run(msg="hello")

    cmd = mock_terminal.run.call_args[0][0]
    assert "-m opencode/fast" in cmd
    assert "--executor" in cmd


def test_run_task_passes_runner_model_from_config(mock_manager, tmp_path):
    input_file = tmp_path / "input.md"
    input_file.write_text("# Do\n\nsomething\n")

    with patch("owrap.commands.run_cmd.Terminal") as mock_terminal_cls, \
         patch("owrap.commands.run_cmd._pool_active", return_value=False), \
         patch("owrap.commands.run_cmd.get_workspace_path", return_value=Path("/tmp/ws")), \
         patch("owrap.utils.paths.get_self_path", return_value=Path("/tmp/fake_self.md")), \
         patch("owrap.utils.paths.resolve_general_instruction_path", return_value=Path("/tmp/fake_instr.md")), \
         patch(
             "owrap.commands.run_cmd._read_config",
             return_value={"runner_model": EXPECTED_RUNNER_MODEL},
         ), \
         patch("owrap.commands.run_cmd.context_path", return_value=tmp_path / "context.md"):
        mock_terminal = MagicMock()
        mock_terminal.run.return_value = {"returncode": 0, "stdout": ""}
        mock_terminal_cls.return_value = mock_terminal

        from owrap.commands.run_cmd import RunRunner
        runner = RunRunner(mock_manager)
        with pytest.raises(SystemExit):
            runner.run(input_path=input_file)

    cmd = mock_terminal.run.call_args[0][0]
    assert f"-m {EXPECTED_RUNNER_MODEL}" in cmd
    assert "--executor" in cmd


def test_exec_passes_runner_model_from_config(mock_manager):
    plan_file = Path("/tmp/fake_plan.md")
    plan_file.write_text("## [ACTIVE] test\n")
    mock_manager.session_id = "test123"

    with patch("owrap.commands.exec.get_plan_path", return_value=plan_file), \
         patch("owrap.commands.exec.Terminal") as mock_terminal_cls, \
         patch("owrap.commands.exec._pool_active", return_value=False), \
         patch("owrap.commands.exec.context_path", return_value=Path("/tmp/fake_context.md")), \
         patch("owrap.commands.exec.get_workspace_path", return_value=Path("/tmp/ws")), \
         patch(
             "owrap.commands.exec._read_config",
             return_value={"runner_model": EXPECTED_RUNNER_MODEL},
         ):
        mock_terminal = MagicMock()
        mock_terminal.run.return_value = {"returncode": 0, "stdout": ""}
        mock_terminal_cls.return_value = mock_terminal

        from owrap.commands.exec import ExecRunner
        runner = ExecRunner(mock_manager)
        with pytest.raises(SystemExit):
            runner.run()

    cmd = mock_terminal.run.call_args[0][0]
    assert f"-m {EXPECTED_RUNNER_MODEL}" in cmd
    assert "--executor" in cmd


def test_exec_cli_model_overrides_config(mock_manager):
    plan_file = Path("/tmp/fake_plan.md")
    plan_file.write_text("## [ACTIVE] test\n")
    mock_manager.session_id = "test123"

    with patch("owrap.commands.exec.get_plan_path", return_value=plan_file), \
         patch("owrap.commands.exec.Terminal") as mock_terminal_cls, \
         patch("owrap.commands.exec._pool_active", return_value=False), \
         patch("owrap.commands.exec.context_path", return_value=Path("/tmp/fake_context.md")), \
         patch("owrap.commands.exec.get_workspace_path", return_value=Path("/tmp/ws")), \
         patch(
             "owrap.commands.exec._read_config",
             return_value={"runner_model": EXPECTED_RUNNER_MODEL},
         ):
        mock_terminal = MagicMock()
        mock_terminal.run.return_value = {"returncode": 0, "stdout": ""}
        mock_terminal_cls.return_value = mock_terminal

        from owrap.commands.exec import ExecRunner
        runner = ExecRunner(mock_manager, model="opencode/test-override")
        with pytest.raises(SystemExit):
            runner.run()

    cmd = mock_terminal.run.call_args[0][0]
    assert "-m opencode/test-override" in cmd
    assert EXPECTED_RUNNER_MODEL not in cmd
    assert "--executor" in cmd


def test_fallback_passes_runner_model_from_config(tmp_path):
    target = tmp_path / "task.md"
    target.write_text("## Do\n\nhello\n")

    with patch("owrap.commands.fallback.Terminal") as mock_terminal_cls, \
         patch(
             "owrap.commands.fallback._read_config",
             return_value={"runner_model": EXPECTED_RUNNER_MODEL},
         ):
        mock_terminal = MagicMock()
        mock_terminal.run.return_value = {"pid": 12345}
        mock_terminal.is_running.return_value = False
        mock_terminal.pop_clean_output.return_value = ""
        mock_terminal._process.poll.return_value = 0
        mock_terminal.model = None
        mock_terminal_cls.return_value = mock_terminal

        from owrap.commands.fallback import FallbackRunner
        runner = FallbackRunner()
        with pytest.raises(SystemExit):
            runner.run(str(target))

    cmd = mock_terminal.run.call_args[0][0]
    assert f"-m {EXPECTED_RUNNER_MODEL}" in cmd
    assert "--executor" in cmd
