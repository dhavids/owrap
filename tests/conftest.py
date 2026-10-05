import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Select test state before importing owrap, whose paths are fixed at import time.
DEV_ROOT = Path(__file__).resolve().parents[1]
if DEV_ROOT.parent.name != "dev":
    raise RuntimeError("owrap tests must run from the dev/owrap checkout")

test_runs_dir = DEV_ROOT / "files" / "test-runs"
test_runs_dir.mkdir(parents=True, exist_ok=True)
_test_home = tempfile.TemporaryDirectory(prefix="pytest-", dir=test_runs_dir)
TEST_HOME = Path(_test_home.name)
os.environ["OWRAP_HOME"] = str(TEST_HOME)
os.environ["OWRAP_TEST_MODE"] = "1"
for name in (
    "SESSION_ID", "CLAUDE_CODE_SESSION_ID", "CODEX_SESSION_ID",
    "OPENCODE_RUN_ID", "OWRAP_SESSION", "OWRAP_SESSION_ID",
    "OWRAP_RESEARCH", "OWRAP_SERVER_URL",
):
    os.environ.pop(name, None)

config_dir = TEST_HOME / "configs"
config_dir.mkdir()
dev_config_dir = DEV_ROOT / "files" / "state" / "configs"
base_config = json.loads((dev_config_dir / "base.json").read_text())
workspace_config = json.loads((dev_config_dir / "marl-dev.json").read_text())
base_config.update(
    server_port_base=15096, max_servers=1, min_servers=2,
    default_workspace="pytest",
)
workspace_config.update(
    workspace=str(TEST_HOME / "workspace"),
    research_root=str(TEST_HOME / "workspace" / "docs" / "research"),
)
(config_dir / "base.json").write_text(json.dumps(base_config))
(config_dir / "pytest.json").write_text(json.dumps(workspace_config))
test_workspace = TEST_HOME / "workspace"
test_research = test_workspace / "docs" / "research"
test_research.mkdir(parents=True)
(test_workspace / "AGENTS.md").write_text("# Test instructions\n")
(test_workspace / "CLAUDE.md").write_text("# Test instructions\n")
(test_research / "self.md").write_text("# Test research\n")

import owrap
from owrap.manager import Manager

if not Path(owrap.__file__).resolve().is_relative_to(DEV_ROOT):
    raise RuntimeError("pytest imported owrap from outside the dev checkout")


@pytest.fixture(scope="session")
def live_config():
    """
    Load the development config copied into this test run's private home.
    """
    from owrap.utils.paths import _read_config
    return _read_config()


@pytest.fixture(autouse=True)
def isolate_session_env(monkeypatch):
    """
    Hide live session IDs; monkeypatch restores them after each test.
    """
    for name in (
        "SESSION_ID", "CLAUDE_CODE_SESSION_ID", "CODEX_SESSION_ID",
        "OPENCODE_RUN_ID", "OWRAP_SESSION", "OWRAP_SESSION_ID",
        "OWRAP_RESEARCH",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def isolate_owrap_dirs(tmp_path, monkeypatch):
    """
    Redirect all owrap output directories to the test's temporary path.
    """
    monkeypatch.setenv("OWRAP_TEST_MODE", "1")
    dirs = {
        "RUNNING_DIR":      tmp_path / "running",
        "RECENTLY_DONE_DIR": tmp_path / "recently_done",
        "DOCS_DIR":         tmp_path / "docs",
        "SESSIONS_DIR":     tmp_path / "sessions",
        "LOCKS_DIR":        tmp_path / "locks",
        "RUN_DIR":          tmp_path / "sessions" / "f" / "run",
        "RUN_LOG":          tmp_path / "sessions" / "f" / "run" / "log.md",
        "READ_LOG":         tmp_path / "sessions" / "f" / "read" / "log.md",
        "EXEC_LOG":         tmp_path / "sessions" / "f" / "exec" / "log.md",
        "TASKS_DIR":        tmp_path / "sessions" / "f" / "run" / "tasks",
        "FALLBACK_DIR":     tmp_path / "sessions" / "f",
        "FALLBACK_EXEC_DIR": tmp_path / "sessions" / "f" / "exec",
        "FALLBACK_TASK_DIR": tmp_path / "sessions" / "f" / "task",
        "FALLBACK_TASK":    tmp_path / "sessions" / "f" / "task" / "task.md",
        "FALLBACK_EXEC_OUTPUT": (
            tmp_path / "sessions" / "f" / "exec" / "output.log"
        ),
        "FALLBACK_EXEC_LOG": (
            tmp_path / "sessions" / "f" / "exec" / "log.md"
        ),
        "FALLBACK_TASK_OUTPUT": (
            tmp_path / "sessions" / "f" / "task" / "output.log"
        ),
        "FALLBACK_TASK_LOG": (
            tmp_path / "sessions" / "f" / "task" / "log.md"
        ),
        "FALLBACK_EXEC_STATUS": (
            tmp_path / "sessions" / "f" / "exec" / "status.json"
        ),
        "FALLBACK_TASK_STATUS": (
            tmp_path / "sessions" / "f" / "task" / "status.json"
        ),
        "FALLBACK_PLAN": (
            tmp_path / "sessions" / "f" / "exec" / "plan.md"
        ),
            "DAEMON_PID_FILE":  tmp_path / "daemon.pid",
            "DAEMON_STATE_FILE": tmp_path / "daemon.state.json",
    }
    _leaf_file_keys = {
        "RUN_LOG", "READ_LOG", "EXEC_LOG", "TASKS_DIR",
        "FALLBACK_TASK", "FALLBACK_EXEC_OUTPUT", "FALLBACK_EXEC_LOG",
        "FALLBACK_TASK_OUTPUT", "FALLBACK_TASK_LOG", "FALLBACK_EXEC_STATUS",
            "FALLBACK_TASK_STATUS", "FALLBACK_PLAN",
            "DAEMON_PID_FILE", "DAEMON_STATE_FILE",
    }
    for k, d in dirs.items():
        if k not in _leaf_file_keys:
            d.mkdir(parents=True, exist_ok=True)

    patches = [patch(f"owrap.utils.paths.{k}", v) for k, v in dirs.items()]
    patches.append(patch("owrap.manager.Manager._kill_port_occupant"))
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
        patch("owrap.commands.run.FALLBACK_TASK",
              dirs["FALLBACK_TASK"]),
        patch("owrap.commands.run.RunRunner.FALLBACK_TASK",
              dirs["FALLBACK_TASK"]),
        patch("owrap.commands.read.FALLBACK_TASK",
              dirs["FALLBACK_TASK"]),
        patch("owrap.commands.read.ReadRunner.FALLBACK_TASK",
              dirs["FALLBACK_TASK"]),
        patch("owrap.commands.get.FALLBACK_PLAN",
              dirs["FALLBACK_PLAN"]),
        patch("owrap.commands.get.FALLBACK_TASK",
              dirs["FALLBACK_TASK"]),
        patch("owrap.commands.get.FALLBACK_EXEC_OUTPUT",
              dirs["FALLBACK_EXEC_OUTPUT"]),
        patch("owrap.commands.get.FALLBACK_TASK_OUTPUT",
              dirs["FALLBACK_TASK_OUTPUT"]),
        patch("owrap.utils.session.resolver.SESSIONS_DIR",
              dirs["SESSIONS_DIR"]),
        patch("owrap.utils.session.resolver.BY_CCSID_DIR",
              dirs["SESSIONS_DIR"] / "by_ccsid"),
        patch("owrap.utils.session.resolver.BY_OPENCODE_RUN_ID_DIR",
              dirs["SESSIONS_DIR"] / "by_opencode_run_id"),
        patch(
            "owrap.utils.session.resolver.BY_CODEX_SESSION_ID_DIR",
            dirs["SESSIONS_DIR"] / "by_codex_session_id",
        ),
            patch("owrap.session.start.BY_CCSID_DIR",
              dirs["SESSIONS_DIR"] / "by_ccsid"),
        patch("owrap.session.start.BY_OPENCODE_RUN_ID_DIR",
              dirs["SESSIONS_DIR"] / "by_opencode_run_id"),
        patch("owrap.session.start.BY_CODEX_SESSION_ID_DIR",
              dirs["SESSIONS_DIR"] / "by_codex_session_id"),
        patch("owrap.session.stop.BY_CCSID_DIR",
              dirs["SESSIONS_DIR"] / "by_ccsid"),
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
