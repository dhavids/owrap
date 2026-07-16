import sys
from pathlib import Path
from unittest.mock import patch

import pytest


def test_stop_force_kills_servers_via_kill_servers_runner(tmp_path):
    """--force must actually kill servers (was calling undefined Manager.stop_all and crashing)."""
    from owrap.session.stop import StopRunner

    fake_session_dir = tmp_path / "owrap_home"
    fake_session_dir.mkdir()
    fake_by_ccsid = tmp_path / "by_ccsid"

    with patch("owrap.session.stop.SESSION_DIR", fake_session_dir), \
         patch("owrap.session.stop.BY_CCSID_DIR", fake_by_ccsid), \
         patch("owrap.session.stop.list_sessions", return_value=[]), \
         patch("owrap.session.stop.KillServersRunner") as mock_ksr_cls:
        runner = StopRunner(manager=None)
        runner.run(force=True, no_exit=True)

    mock_ksr_cls.assert_called_once_with()
    mock_ksr_cls.return_value.run.assert_called_once_with()


def test_trim_command_removed():
    """owrap trim was removed (it only ever called an undefined Manager.trim_idle_servers)."""
    with patch.object(sys, "argv", ["owrap", "trim"]):
        from owrap.runner import main as runner_main
        with pytest.raises(SystemExit) as exc_info:
            runner_main()
        assert exc_info.value.code != 0
