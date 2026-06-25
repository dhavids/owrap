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


@pytest.fixture(autouse=True)
def isolate_owrap_dirs(tmp_path, monkeypatch):
    """Redirect all owrap output dirs to tmp_path so tests don't pollute live state."""
    monkeypatch.delenv("OWRAP_SESSION", raising=False)
    monkeypatch.delenv("OWRAP_RESEARCH", raising=False)
    dirs = {
        "RUNNING_DIR":      tmp_path / "running",
        "RECENTLY_DONE_DIR": tmp_path / "recently_done",
        "TASK_LOGS_DIR":    tmp_path / "task_logs",
        "MSG_LOGS_DIR":     tmp_path / "msg_logs",
        "EXEC_OUTPUT_DIR":  tmp_path / "exec_output",
        "PLANS_DIR":        tmp_path / "plans",
        "DOCS_DIR":         tmp_path / "docs",
        "SESSIONS_DIR":     tmp_path / "docs" / "sessions",
        "RUN_DIR":          tmp_path / "docs" / "run",
        "RUN_LOG":          tmp_path / "docs" / "run" / "log.md",
        "RUN_OUTPUT_DIR":   tmp_path / "docs" / "run" / "output",
        "READ_DIR":         tmp_path / "docs" / "read",
        "READ_LOG":         tmp_path / "docs" / "read" / "log.md",
        "READ_OUTPUT_DIR":  tmp_path / "docs" / "read" / "output",
        "EXEC_DIR":         tmp_path / "docs" / "exec",
        "EXEC_LOG":         tmp_path / "docs" / "exec" / "log.md",
        "TASKS_DIR":        tmp_path / "docs" / "run" / "tasks",
        "CONTEXT_DIR":      tmp_path / "docs" / "context",
    }
    _log_keys = {"RUN_LOG", "READ_LOG", "EXEC_LOG", "TASKS_DIR", "RUN_OUTPUT_DIR"}
    for k, d in dirs.items():
        if k not in _log_keys:
            d.mkdir(parents=True, exist_ok=True)

    patches = [patch(f"owrap.utils.paths.{k}", v) for k, v in dirs.items()]
    patches += [
        patch("owrap.manager.RUN_LOG", dirs["RUN_LOG"]),
        patch("owrap.manager.EXEC_LOG", dirs["EXEC_LOG"]),
        patch("owrap.manager.READ_LOG", dirs["READ_LOG"]),
        patch("owrap.manager.TASKS_DIR", dirs["TASKS_DIR"]),
        patch("owrap.manager.RUN_OUTPUT_DIR", dirs["RUN_OUTPUT_DIR"]),
        patch("owrap.manager.Manager.TASKS_DIR", dirs["TASKS_DIR"]),
        patch("owrap.manager.Manager.OUTPUT_DIR", dirs["RUN_OUTPUT_DIR"]),
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
