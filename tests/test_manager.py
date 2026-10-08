import os
import time
from unittest.mock import patch, MagicMock

import pytest


def _make_manager():
    from owrap.manager import Manager
    manager = Manager.__new__(Manager)
    manager.session_id = ""
    manager.research = ""
    manager._t_invocation = time.time()
    manager._t_cmd_start = None
    manager._t_cmd_end = None
    manager._state_file = str(Manager.STATE_FILE)
    manager._log_file = None
    return manager


def test_register_and_complete_task(tmp_path):
    state_file = tmp_path / "manager.json"
    manager = _make_manager()
    manager.STATE_FILE = str(state_file)

    manager._write_state({"pid": 12345, "url": "http://localhost:4096", "port": 4096, "tasks": {}})

    manager.register_task(1)
    state = manager._read_state()
    assert isinstance(state["tasks"]["1"], dict)
    assert state["tasks"]["1"]["status"] == "active"
    assert "invocation_time" in state["tasks"]["1"]

    manager.complete_task(1)
    state = manager._read_state()
    assert state["tasks"]["1"]["status"] == "done"


def test_complete_task_timing(tmp_path):
    state_file = tmp_path / "manager.json"
    manager = _make_manager()
    manager.STATE_FILE = str(state_file)
    manager._t_invocation = t0 = time.time()

    manager.register_task(1)
    manager._t_cmd_start = t1 = t0 + 0.5
    manager._t_cmd_end = t2 = t0 + 2.3
    manager.complete_task(1)

    state = manager._read_state()
    entry = state["tasks"]["1"]
    assert entry["status"] == "done"
    assert entry["cmd_start"] == t1
    assert entry["cmd_end"] == t2
    assert entry["duration_s"] == 1.8
    assert entry["total_s"] == 2.3


@pytest.mark.parametrize("log_name", ["task2.log", "task2_123456.log"])
def test_cleanup_removes_done_task_files(tmp_path, log_name):
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (tasks_dir / "task2.md").write_text("done task")
    (output_dir / log_name).write_text("log")

    state_file = tmp_path / "manager.json"
    manager = _make_manager()
    manager.STATE_FILE = str(state_file)
    manager.TASKS_DIR = tasks_dir

    manager._write_state({"pid": 12345, "url": "http://localhost:4096", "port": 4096, "tasks": {"task2": {"status": "done", "invocation_time": time.time()}}})

    manager.cleanup_done_tasks()

    assert not (tasks_dir / "task2.md").exists()
    state = manager._read_state()
    assert "task2" not in state["tasks"]


def test_cleanup_keeps_active_task_when_server_alive(tmp_path):
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (tasks_dir / "task1.md").write_text("active task")

    state_file = tmp_path / "manager.json"
    manager = _make_manager()
    manager.STATE_FILE = str(state_file)
    manager.TASKS_DIR = tasks_dir

    manager._write_state({"pid": 12345, "url": "http://localhost:4096", "port": 4096, "tasks": {"task1": {"status": "active", "invocation_time": time.time()}}})

    with patch("os.kill", return_value=None):
        manager.cleanup_done_tasks()

    assert (tasks_dir / "task1.md").exists()
    state = manager._read_state()
    assert "task1" in state["tasks"]


def test_cleanup_removes_active_task_when_server_dead(tmp_path):
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (tasks_dir / "task1.md").write_text("orphaned task")
    (output_dir / "task1.log").write_text("orphaned log")

    state_file = tmp_path / "manager.json"
    manager = _make_manager()
    manager.STATE_FILE = str(state_file)
    manager.TASKS_DIR = tasks_dir

    manager._write_state({"pid": 99999, "url": "http://localhost:4096", "port": 4096, "tasks": {"task1": {"status": "active", "invocation_time": time.time()}}})

    with patch("os.kill", side_effect=OSError):
        manager.cleanup_done_tasks()

    assert not (tasks_dir / "task1.md").exists()
    state = manager._read_state()
    assert "task1" not in state["tasks"]


def test_cleanup_compat_with_old_string_format(tmp_path):
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (tasks_dir / "task3.md").write_text("old format done")
    (output_dir / "task3.log").write_text("old log")

    state_file = tmp_path / "manager.json"
    manager = _make_manager()
    manager.STATE_FILE = str(state_file)
    manager.TASKS_DIR = tasks_dir

    manager._write_state({"pid": 12345, "url": "http://localhost:4096", "port": 4096, "tasks": {"task3": "done"}})

    manager.cleanup_done_tasks()

    assert not (tasks_dir / "task3.md").exists()
    state = manager._read_state()
    assert "task3" not in state["tasks"]


def test_legacy_dirs_not_created_with_session(monkeypatch, isolate_owrap_dirs):
    monkeypatch.setenv("OWRAP_SESSION", "testsid")
    from owrap.manager import Manager
    Manager()
    assert not isolate_owrap_dirs["TASKS_DIR"].exists()


def test_legacy_dirs_created_without_session(monkeypatch, isolate_owrap_dirs):
    monkeypatch.delenv("OWRAP_SESSION", raising=False)
    from owrap.manager import Manager
    Manager()
    assert isolate_owrap_dirs["TASKS_DIR"].exists()


def test_start_resolves_pid_from_marker(tmp_path, monkeypatch):
    manager = _make_manager()
    manager._state_file = str(tmp_path / "state.json")
    manager._logger = None
    monkeypatch.setattr("owrap.manager.SESSION_DIR", tmp_path)
    monkeypatch.setattr("owrap.manager.SERVER_LOGS_DIR", tmp_path / "logs")
    (tmp_path / "logs").mkdir(parents=True, exist_ok=True)

    def fake_popen(*args, **kwargs):
        kwargs["stdout"].write(
            "OWRAP_PID=22222\n"
            "opencode server listening on http://127.0.0.1:4096\n"
        )
        kwargs["stdout"].flush()
        m = MagicMock()
        m.pid = 11111
        m.poll.return_value = None
        return m

    with patch("subprocess.Popen", side_effect=fake_popen), \
         patch("time.sleep", return_value=None):
        url = manager.start(port=4096)

    assert url == "http://127.0.0.1:4096"
    state = manager._read_state()
    assert state["pid"] == 22222
    assert (tmp_path / "logs" / "owrap_22222.log").exists()
    assert not list(tmp_path.glob("owrap_start_*.log"))


def test_start_falls_back_to_popen_pid_without_marker(tmp_path, monkeypatch):
    manager = _make_manager()
    manager._state_file = str(tmp_path / "state.json")
    manager._logger = None
    monkeypatch.setattr("owrap.manager.SESSION_DIR", tmp_path)
    monkeypatch.setattr("owrap.manager.SERVER_LOGS_DIR", tmp_path / "logs")
    (tmp_path / "logs").mkdir(parents=True, exist_ok=True)

    def fake_popen(*args, **kwargs):
        kwargs["stdout"].write(
            "opencode server listening on http://127.0.0.1:4097\n"
        )
        kwargs["stdout"].flush()
        m = MagicMock()
        m.pid = 11111
        m.poll.return_value = None
        return m

    with patch("subprocess.Popen", side_effect=fake_popen), \
         patch("time.sleep", return_value=None):
        url = manager.start(port=4097)

    assert url == "http://127.0.0.1:4097"
    state = manager._read_state()
    assert state["pid"] == 11111


def test_resolve_log_file_always_none(tmp_path):
    manager = _make_manager()
    manager._state_file = str(tmp_path / "state.json")
    manager._resolve_log_file()
    assert manager._log_file is None

    manager._write_state({"pid": os.getpid(), "url": "http://x", "port": 1})
    manager._resolve_log_file()
    assert manager._log_file is None


def test_create_context_fresh_file_has_no_phase_or_research_root(monkeypatch):
    manager = _make_manager()
    manager.session_id = "sid01"
    monkeypatch.setattr(
        "owrap.manager._read_config",
        lambda: {"docs_root": "/docs/root", "venv": "~/e-swarm"},
    )

    manager.create_context()

    text = manager.context_path.read_text()
    assert "docs_root: /docs/root" in text
    assert "venv: ~/e-swarm" in text
    assert "phase:" not in text
    assert "research_root:" not in text


def test_create_context_refreshes_docs_root_and_venv_on_existing_file(
    monkeypatch,
):
    manager = _make_manager()
    manager.session_id = "sid02"
    manager.context_path.parent.mkdir(parents=True, exist_ok=True)
    manager.context_path.write_text(
        "## Session\n\nsession: sid02\nresearch_root: /old/root\n"
        "phase: 1\nvenv: /old/venv\nlast_updated: 2026-01-01 00:00\n"
        "\n## Focus\n\nkeep this\n"
    )
    monkeypatch.setattr(
        "owrap.manager._read_config",
        lambda: {"docs_root": "/new/root", "venv": "/new/venv"},
    )

    manager.create_context()

    text = manager.context_path.read_text()
    assert "docs_root: /new/root" in text
    assert "venv: /new/venv" in text
    assert "phase:" not in text
    assert "research_root:" not in text
    assert "keep this" in text


def test_create_context_mirrors_ctx_status_from_ctx_state(monkeypatch):
    from owrap.utils.paths import session_ctx_state_path
    import json as _json
    manager = _make_manager()
    manager.session_id = "sid03"
    monkeypatch.setattr(
        "owrap.manager._read_config", lambda: {"docs_root": "/docs/root"},
    )
    state_path = session_ctx_state_path("sid03")
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(_json.dumps({"ctx": {"status": "failed"}}))

    manager.create_context()
    assert "ctx_status: failed" in manager.context_path.read_text()

    state_path.write_text(_json.dumps({"ctx": {"status": "ok"}}))
    manager.create_context()
    text = manager.context_path.read_text()
    assert "ctx_status: ok" in text
    assert text.count("ctx_status:") == 1


def _make_runner(manager):
    from owrap.base import BaseRunner

    class _Runner(BaseRunner):
        def run(self, args):
            return 0

    return _Runner(manager)


def test_write_sentinel_registers_running_task(tmp_path):
    import json as _json
    from owrap.utils.paths import session_ctx_state_path
    manager = _make_manager()
    manager.session_id = "sid10"
    manager.get_server_url = lambda: ""
    runner = _make_runner(manager)

    sentinel_path = runner._write_sentinel("42", "Do the thing", kind="task")

    state = _json.loads(session_ctx_state_path("sid10").read_text())
    entry = state["running"][sentinel_path.name]
    assert entry["title"] == "Do the thing"
    assert entry["kind"] == "task"


def test_complete_sentinel_clears_running_task(tmp_path):
    import json as _json
    from owrap.utils.paths import session_ctx_state_path
    manager = _make_manager()
    manager.session_id = "sid11"
    manager.get_server_url = lambda: ""
    runner = _make_runner(manager)

    sentinel_path = runner._write_sentinel("43", "Do another thing", kind="task")
    state = _json.loads(session_ctx_state_path("sid11").read_text())
    assert sentinel_path.name in state["running"]

    runner._complete_sentinel(sentinel_path, rc=0)

    state = _json.loads(session_ctx_state_path("sid11").read_text())
    assert state["running"] == {}
