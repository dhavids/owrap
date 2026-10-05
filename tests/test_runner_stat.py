from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


def test_stat_starts_daemon_for_context_manager():
    from owrap.runner import _cmd_stat

    with (
        patch("owrap.runner._read_config", return_value={
            "owrap_runner_enabled": False,
            "owrap_context_manager_enabled": True,
        }),
        patch("owrap.utils.dispatch.pool._ensure_daemon") as ensure,
        patch("owrap.session.stat.StatRunner") as stat,
        pytest.raises(SystemExit) as exc_info,
    ):
        stat.return_value.run.return_value = 0
        _cmd_stat(SimpleNamespace(), MagicMock(), MagicMock(), False)

    ensure.assert_called_once_with()
    assert exc_info.value.code == 0


def test_stat_leaves_daemon_stopped_when_services_are_disabled():
    from owrap.runner import _cmd_stat

    with (
        patch("owrap.runner._read_config", return_value={
            "owrap_runner_enabled": False,
            "owrap_context_manager_enabled": False,
        }),
        patch("owrap.utils.dispatch.pool._ensure_daemon") as ensure,
        patch("owrap.session.stat.StatRunner") as stat,
        pytest.raises(SystemExit),
    ):
        stat.return_value.run.return_value = 0
        _cmd_stat(SimpleNamespace(), MagicMock(), MagicMock(), False)

    ensure.assert_not_called()
