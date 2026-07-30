import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def test_extract_agent_summary_with_summary_header_only():
    from owrap.commands.agents import _extract_agent_summary

    output = "some output\n\n## Summary\nThis is the summary."
    result = _extract_agent_summary(output)
    assert result == "This is the summary."


def test_extract_agent_summary_with_summary_then_another_heading():
    from owrap.commands.agents import _extract_agent_summary

    output = "some output\n\n## Summary\nSummary content here.\n\n## Next Section\nMore stuff."
    result = _extract_agent_summary(output)
    assert result == "Summary content here.\n\n## Next Section\nMore stuff."


def test_extract_agent_summary_no_summary_header():
    from owrap.commands.agents import _extract_agent_summary

    output = "just some output with no summary header at all"
    result = _extract_agent_summary(output)
    assert "[no '## Summary' header found" in result
    assert "raw tail" in result


def test_agents_runner_clear_removes_log_and_dir(tmp_path, mock_manager):
    from owrap.commands.agents import AgentsRunner
    from owrap.utils.paths import session_agent_log_path, session_agent_full_log_dir

    sid = mock_manager.session_id
    log_path = session_agent_log_path(sid)
    full_log_dir = session_agent_full_log_dir(sid)

    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("old log")
    full_log_dir.mkdir(parents=True, exist_ok=True)
    (full_log_dir / "some.log").write_text("some log")

    assert log_path.exists()
    assert full_log_dir.exists()

    runner = AgentsRunner(mock_manager)
    with pytest.raises(SystemExit) as exc_info:
        runner.run(action="clear")
    assert exc_info.value.code == 0

    assert not log_path.exists()
    assert not full_log_dir.exists()


def test_agents_runner_clear_no_error_when_nothing_exists(mock_manager):
    from owrap.commands.agents import AgentsRunner

    runner = AgentsRunner(mock_manager)
    with pytest.raises(SystemExit) as exc_info:
        runner.run(action="clear")
    assert exc_info.value.code == 0


def test_agents_runner_clear_no_session():
    from owrap.commands.agents import AgentsRunner

    manager = MagicMock()
    manager.session_id = None

    runner = AgentsRunner(manager)
    with pytest.raises(SystemExit) as exc_info:
        runner.run(action="clear")
    assert exc_info.value.code == 1


def test_agents_runner_init_with_model(mock_manager):
    from owrap.commands.agents import AgentsRunner

    runner = AgentsRunner(mock_manager, model="test-model")
    assert runner.model == "test-model"


def test_agents_run_agent_dispatch_path(tmp_path, mock_manager):
    """Test that _run_agent builds the correct command and creates expected files."""
    from owrap.commands.agents import AgentsRunner, _AGENT_INSTRUCTIONS_SUFFIX
    from owrap.utils.paths import session_agent_full_log_dir

    mock_manager.ensure_running.return_value = "http://localhost:4096"

    sid = mock_manager.session_id
    agent_log_dir = session_agent_full_log_dir(sid)
    agent_log_dir.mkdir(parents=True, exist_ok=True)

    with patch("owrap.commands.agents.Terminal") as mock_terminal_cls, \
         patch("owrap.commands.agents._pool_active", return_value=False):
        mock_terminal = MagicMock()
        mock_terminal.run.return_value = {"returncode": 0, "stdout": "## Summary\nAgent done."}
        mock_terminal_cls.return_value = mock_terminal

        runner = AgentsRunner(mock_manager)
        with pytest.raises(SystemExit) as exc_info:
            runner.run_agent(data="test agent instruction", agent_id="test1")

        assert exc_info.value.code == 0

        call_args = mock_terminal.run.call_args[0][0]
        assert "--attach" in call_args
        assert "http://localhost:4096" in call_args
        assert "test agent instruction" in call_args
        assert "Aim to finish this task within 120 seconds" in call_args
        assert "## Summary" in call_args


def test_clear_skipped_when_agent_job_running(tmp_path, mock_manager, monkeypatch):
    """When another agent-kind job is running for the same session, --clear is skipped."""
    from owrap.commands import agents as agents_mod
    from owrap.commands.agents import AgentsRunner
    from owrap.utils.paths import (
        session_agent_log_path, session_agent_full_log_dir,
    )

    sid = mock_manager.session_id
    log_path = session_agent_log_path(sid)
    full_log_dir = session_agent_full_log_dir(sid)

    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("old log")
    full_log_dir.mkdir(parents=True, exist_ok=True)
    (full_log_dir / "some.log").write_text("some log")

    running_dir = tmp_path / "running"
    running_dir.mkdir(parents=True, exist_ok=True)
    sentinel_data = {
        "pid": os.getpid(),
        "task_id": "other_agent",
        "session_id": sid,
        "kind": "agent",
        "title": "other agent task",
        "started": 0,
    }
    sentinel_file = running_dir / f"agentother_agent_{sid}.json"
    sentinel_file.write_text(json.dumps(sentinel_data))

    with patch.object(agents_mod, "RUNNING_DIR", running_dir):
        runner = AgentsRunner(mock_manager)
        with pytest.raises(SystemExit) as exc_info:
            runner.run(action="clear")
        assert exc_info.value.code == 0

    # Directory and log should still exist because clear was skipped
    assert log_path.exists()
    assert full_log_dir.exists()
    assert (full_log_dir / "some.log").exists()
