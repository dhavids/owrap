from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from owrap.manager import Manager


@pytest.fixture(scope="session", autouse=True)
def kill_servers_around_tests():
    """Kill all servers before and after the test session."""
    from owrap.session.stop import KillServersRunner
    KillServersRunner().run()
    yield
    KillServersRunner().run()


@pytest.fixture(scope="session")
def live_config():
    """Load the merged owrap config from the real home directory so tests track model changes.

    This intentionally reads the live config rather than hardcoding model names; when the
    exec_model or fast_model changes in ~/.owrap/configs, tests that assert on the passed
    model string update automatically.
    """
    from owrap.utils.paths import _read_config
    return _read_config()


@pytest.fixture(autouse=True)
def isolate_owrap_dirs(tmp_path, monkeypatch):
    """Redirect all owrap output dirs to tmp_path so tests don't pollute live state."""
    monkeypatch.delenv("OWRAP_SESSION", raising=False)
    monkeypatch.delenv("OWRAP_RESEARCH", raising=False)
    monkeypatch.setenv("OWRAP_TEST_MODE", "1")
    dirs = {
        "RUNNING_DIR":      tmp_path / "running",
        "RECENTLY_DONE_DIR": tmp_path / "recently_done",
        "DOCS_DIR":         tmp_path / "docs",
        "SESSIONS_DIR":     tmp_path / "docs" / "sessions",
        "RUN_DIR":          tmp_path / "docs" / "run",
        "RUN_LOG":          tmp_path / "docs" / "run" / "log.md",
        "READ_LOG":         tmp_path / "docs" / "read" / "log.md",
        "EXEC_LOG":         tmp_path / "docs" / "exec" / "log.md",
        "TASKS_DIR":        tmp_path / "docs" / "run" / "tasks",
        "FALLBACK_DIR":     tmp_path / "docs" / "f",
        "FALLBACK_EXEC_DIR": tmp_path / "docs" / "f" / "exec",
        "FALLBACK_TASK_DIR": tmp_path / "docs" / "f" / "task",
        "FALLBACK_TASK":    tmp_path / "docs" / "f" / "task" / "task.md",
        "FALLBACK_EXEC_OUTPUT": tmp_path / "docs" / "f" / "exec" / "output.log",
        "FALLBACK_EXEC_LOG":    tmp_path / "docs" / "f" / "exec" / "log.md",
        "FALLBACK_TASK_OUTPUT": tmp_path / "docs" / "f" / "task" / "output.log",
        "FALLBACK_TASK_LOG":    tmp_path / "docs" / "f" / "task" / "log.md",
        "FALLBACK_EXEC_STATUS": tmp_path / "docs" / "f" / "exec" / "status.json",
        "FALLBACK_TASK_STATUS": tmp_path / "docs" / "f" / "task" / "status.json",
        "FALLBACK_PLAN":    tmp_path / "docs" / "f" / "exec" / "plan.md",
    }
    _leaf_file_keys = {
        "RUN_LOG", "READ_LOG", "EXEC_LOG", "TASKS_DIR",
        "FALLBACK_TASK", "FALLBACK_EXEC_OUTPUT", "FALLBACK_EXEC_LOG",
        "FALLBACK_TASK_OUTPUT", "FALLBACK_TASK_LOG", "FALLBACK_EXEC_STATUS",
        "FALLBACK_TASK_STATUS", "FALLBACK_PLAN",
    }
    for k, d in dirs.items():
        if k not in _leaf_file_keys:
            d.mkdir(parents=True, exist_ok=True)

    patches = [patch(f"owrap.utils.paths.{k}", v) for k, v in dirs.items()]
    patches += [
        patch("owrap.manager.RUN_LOG", dirs["RUN_LOG"]),
        patch("owrap.manager.EXEC_LOG", dirs["EXEC_LOG"]),
        patch("owrap.manager.READ_LOG", dirs["READ_LOG"]),
        patch("owrap.manager.TASKS_DIR", dirs["TASKS_DIR"]),
        patch("owrap.manager.Manager.TASKS_DIR", dirs["TASKS_DIR"]),
    ]
    patches += [
        patch("owrap.commands.fallback.FALLBACK_EXEC_OUTPUT",
              dirs["FALLBACK_EXEC_OUTPUT"]),
        patch("owrap.commands.fallback.FALLBACK_EXEC_LOG",
              dirs["FALLBACK_EXEC_LOG"]),
        patch("owrap.commands.fallback.FALLBACK_EXEC_STATUS",
              dirs["FALLBACK_EXEC_STATUS"]),
        patch("owrap.commands.fallback.FALLBACK_TASK_OUTPUT",
              dirs["FALLBACK_TASK_OUTPUT"]),
        patch("owrap.commands.fallback.FALLBACK_TASK_LOG",
              dirs["FALLBACK_TASK_LOG"]),
        patch("owrap.commands.fallback.FALLBACK_TASK_STATUS",
              dirs["FALLBACK_TASK_STATUS"]),
        patch("owrap.commands.fallback.FallbackRunner.EXEC_OUTPUT",
              dirs["FALLBACK_EXEC_OUTPUT"]),
        patch("owrap.commands.fallback.FallbackRunner.EXEC_LOG",
              dirs["FALLBACK_EXEC_LOG"]),
        patch("owrap.commands.fallback.FallbackRunner.EXEC_STATUS",
              dirs["FALLBACK_EXEC_STATUS"]),
        patch("owrap.commands.fallback.FallbackRunner.TASK_OUTPUT",
              dirs["FALLBACK_TASK_OUTPUT"]),
        patch("owrap.commands.fallback.FallbackRunner.TASK_LOG",
              dirs["FALLBACK_TASK_LOG"]),
        patch("owrap.commands.fallback.FallbackRunner.TASK_STATUS",
              dirs["FALLBACK_TASK_STATUS"]),
        patch("owrap.commands.run_cmd.FALLBACK_TASK",
              dirs["FALLBACK_TASK"]),
        patch("owrap.commands.run_cmd.RunRunner.FALLBACK_TASK",
              dirs["FALLBACK_TASK"]),
        patch("owrap.commands.read.FALLBACK_TASK",
              dirs["FALLBACK_TASK"]),
        patch("owrap.commands.read.ReadRunner.FALLBACK_TASK",
              dirs["FALLBACK_TASK"]),
        patch("owrap.commands.get_cmd.FALLBACK_PLAN",
              dirs["FALLBACK_PLAN"]),
        patch("owrap.commands.get_cmd.FALLBACK_TASK",
              dirs["FALLBACK_TASK"]),
        patch("owrap.commands.get_cmd.FALLBACK_EXEC_OUTPUT",
              dirs["FALLBACK_EXEC_OUTPUT"]),
        patch("owrap.commands.get_cmd.FALLBACK_TASK_OUTPUT",
              dirs["FALLBACK_TASK_OUTPUT"]),
    ]

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
    manager.next_task_name = MagicMock(return_value="task_20260613_120000_000001")
    manager.register_task = MagicMock()
    manager.complete_task = MagicMock()
    manager.build_context_summary = MagicMock(return_value="")
    manager.append_context_recent = MagicMock()
    manager.update_frequent_files = MagicMock()
    return manager
