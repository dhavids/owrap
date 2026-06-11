from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from owrap.manager import Manager


@pytest.fixture(scope="session", autouse=True)
def kill_servers_around_tests():
    """Kill all servers before and after the test session."""
    from owrap.session.killservers import KillServersRunner
    KillServersRunner().run()
    yield
    KillServersRunner().run()


@pytest.fixture(autouse=True)
def isolate_owrap_dirs(tmp_path):
    """Redirect all owrap output dirs to tmp_path so tests don't pollute live state."""
    dirs = {
        "RUNNING_DIR":      tmp_path / "running",
        "RECENTLY_DONE_DIR": tmp_path / "recently_done",
        "TASK_LOGS_DIR":    tmp_path / "task_logs",
        "MSG_LOGS_DIR":     tmp_path / "msg_logs",
        "EXEC_OUTPUT_DIR":  tmp_path / "exec_output",
        "PLANS_DIR":        tmp_path / "plans",
    }
    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)

    patches = [patch(f"owrap.utils.paths.{k}", v) for k, v in dirs.items()]
    # Also patch the class-level OUTPUT_DIR used in runners
    exec_patch = patch("owrap.commands.exec.EXEC_OUTPUT_DIR", dirs["EXEC_OUTPUT_DIR"])
    patches.append(exec_patch)

    for p in patches:
        p.start()
    yield dirs
    for p in patches:
        p.stop()


@pytest.fixture
def mock_manager(tmp_path):
    manager = Manager.__new__(Manager)
    manager.session_id = "test123"
    manager.research = "test"
    manager._t_cmd_start = None
    manager._t_cmd_end = None
    manager._t_invocation = None
    type(manager).run_log_path = tmp_path / "run.log"
    type(manager).input_path = tmp_path / "input.md"
    manager._state_file = str(tmp_path / "manager.json")
    manager._log_file = str(tmp_path / "log.txt")
    manager.ensure_running = MagicMock(return_value=None)
    manager.get_server_url = MagicMock(return_value=None)
    manager.t_cmd_start = MagicMock()
    manager.t_cmd_end = MagicMock()
    manager.log_time = MagicMock()
    manager.next_task_id = MagicMock(return_value=1)
    manager.register_task = MagicMock()
    manager.complete_task = MagicMock()
    manager.build_context_summary = MagicMock(return_value="")
    manager.append_context_recent = MagicMock()
    manager.update_frequent_files = MagicMock()
    return manager
