import json
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


def _make_manager():
    from util.misc.opencode.manager import OpenCodeManager
    manager = OpenCodeManager.__new__(OpenCodeManager)
    manager._t_invocation = time.time()
    manager._t_cmd_start = None
    manager._t_cmd_end = None
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


def test_cleanup_removes_done_task_files(tmp_path):
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (tasks_dir / "task2.md").write_text("done task")
    (output_dir / "task2.log").write_text("log")

    state_file = tmp_path / "manager.json"
    manager = _make_manager()
    manager.STATE_FILE = str(state_file)
    manager.TASKS_DIR = tasks_dir
    manager.OUTPUT_DIR = output_dir

    manager._write_state({"pid": 12345, "url": "http://localhost:4096", "port": 4096, "tasks": {"2": {"status": "done", "invocation_time": time.time()}}})

    manager.cleanup_done_tasks()

    assert not (tasks_dir / "task2.md").exists()
    assert not (output_dir / "task2.log").exists()
    state = manager._read_state()
    assert "2" not in state["tasks"]


def test_cleanup_removes_suffixed_logs(tmp_path):
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (tasks_dir / "task2.md").write_text("done task")
    (output_dir / "task2_123456.log").write_text("suffixed log")

    state_file = tmp_path / "manager.json"
    manager = _make_manager()
    manager.STATE_FILE = str(state_file)
    manager.TASKS_DIR = tasks_dir
    manager.OUTPUT_DIR = output_dir

    manager._write_state({"pid": 12345, "url": "http://localhost:4096", "port": 4096, "tasks": {"2": {"status": "done", "invocation_time": time.time()}}})

    manager.cleanup_done_tasks()

    assert not (output_dir / "task2_123456.log").exists()


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
    manager.OUTPUT_DIR = output_dir

    manager._write_state({"pid": 12345, "url": "http://localhost:4096", "port": 4096, "tasks": {"1": {"status": "active", "invocation_time": time.time()}}})

    with patch("os.kill", return_value=None):
        manager.cleanup_done_tasks()

    assert (tasks_dir / "task1.md").exists()
    state = manager._read_state()
    assert "1" in state["tasks"]


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
    manager.OUTPUT_DIR = output_dir

    manager._write_state({"pid": 99999, "url": "http://localhost:4096", "port": 4096, "tasks": {"1": {"status": "active", "invocation_time": time.time()}}})

    with patch("os.kill", side_effect=OSError):
        manager.cleanup_done_tasks()

    assert not (tasks_dir / "task1.md").exists()
    assert not (output_dir / "task1.log").exists()
    state = manager._read_state()
    assert "1" not in state["tasks"]


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
    manager.OUTPUT_DIR = output_dir

    manager._write_state({"pid": 12345, "url": "http://localhost:4096", "port": 4096, "tasks": {"3": "done"}})

    manager.cleanup_done_tasks()

    assert not (tasks_dir / "task3.md").exists()
    assert not (output_dir / "task3.log").exists()
    state = manager._read_state()
    assert "3" not in state["tasks"]
