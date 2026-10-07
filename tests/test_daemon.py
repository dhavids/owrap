from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.runner


class _StopLoop(Exception):
    """
    Break the daemon loop from a mocked sleep call.
    """


def _stop_after(n):
    calls = {"n": 0}

    def _sleep(_):
        calls["n"] += 1
        if calls["n"] >= n:
            raise _StopLoop()
    return _sleep, calls


def test_daemon_keeps_running_when_pool_is_idle(tmp_path):
    """
    The daemon must NOT exit itself just because the pool has been idle —
    only the pool's own servers get recycled on idle, never the daemon
    process. Confirmed by looping well past what used to be the idle-exit
    threshold and seeing it keep going until something else stops it.
    """
    from owrap.commands.daemon import DaemonRunner

    (tmp_path / ".owrap").mkdir(parents=True, exist_ok=True)
    sleep_fn, calls = _stop_after(5)

    with patch("owrap.commands.daemon.get_pool", return_value=[]), \
         patch("owrap.commands.daemon._read_config", return_value={
             "daemon_interval_s": 0.01,
             "owrap_context_manager_enabled": False,
         }), \
         patch("owrap.commands.daemon.time.sleep", side_effect=sleep_fn):
        with pytest.raises(_StopLoop):
            DaemonRunner(MagicMock()).run()

    assert calls["n"] >= 5


def test_daemon_exits_when_runner_and_context_manager_both_disabled(tmp_path):
    from owrap.commands.daemon import DaemonRunner

    with patch("owrap.commands.daemon._read_config", return_value={
        "owrap_runner_enabled": False,
        "owrap_context_manager_enabled": False,
    }):
        with pytest.raises(SystemExit) as exc_info:
            DaemonRunner(MagicMock()).run()
    assert exc_info.value.code == 0


def test_daemon_does_not_replace_running_registered_daemon(tmp_path):
    from owrap.commands.daemon import DaemonRunner

    pid_file = tmp_path / "daemon.pid"
    pid_file.write_text("1")

    with (
        patch("owrap.utils.paths.DAEMON_PID_FILE", pid_file),
        patch("owrap.commands.daemon._read_config", return_value={
            "owrap_runner_enabled": False,
            "owrap_context_manager_enabled": True,
        }),
        patch("owrap.commands.daemon.time.sleep") as sleep,
    ):
        DaemonRunner(MagicMock()).run()

    sleep.assert_not_called()


def test_daemon_runs_when_only_context_manager_enabled(tmp_path):
    """
    The daemon must stay available for context-manager work even when the
    runner (dispatch tooling) is off — they're independently gated.
    """
    from owrap.commands.daemon import DaemonRunner

    (tmp_path / ".owrap").mkdir(parents=True, exist_ok=True)
    sleep_fn, calls = _stop_after(2)
    mock_get_pool = MagicMock(return_value=[])
    mock_ensure_min = MagicMock()
    mock_worker_cls = MagicMock()

    with patch("owrap.commands.daemon.get_pool", mock_get_pool), \
         patch("owrap.commands.daemon.ensure_min_servers", mock_ensure_min), \
         patch("owrap.commands.context_manager.CtxWorkerRunner", mock_worker_cls), \
         patch("owrap.commands.daemon._read_config", return_value={
             "owrap_runner_enabled": False,
             "owrap_context_manager_enabled": True,
             "daemon_interval_s": 0.01,
         }), \
         patch("owrap.commands.daemon.time.sleep", side_effect=sleep_fn):
        with pytest.raises(_StopLoop):
            DaemonRunner(MagicMock()).run()

    assert calls["n"] >= 2
    # Idle cleanup still runs on any leftover servers, disabled or not.
    mock_get_pool.assert_called()
    # Only starting new capacity is skipped while the runner is disabled.
    mock_ensure_min.assert_not_called()


def test_daemon_cleans_up_leftover_server_while_runner_disabled(tmp_path):
    """
    A server left running from before the runner was disabled must still
    get torn down once idle, even though nothing is maintaining capacity
    for it anymore.
    """
    from owrap.commands.daemon import DaemonRunner

    (tmp_path / ".owrap").mkdir(parents=True, exist_ok=True)
    sleep_fn, calls = _stop_after(2)
    leftover_pool = [{"url": "http://127.0.0.1:4096", "pid": 123}]
    mock_shutdown_idle = MagicMock()

    with patch("owrap.commands.daemon.get_pool", return_value=leftover_pool), \
         patch("owrap.commands.daemon._active_load", return_value=0), \
         patch("owrap.commands.daemon.shutdown_idle", mock_shutdown_idle), \
         patch("owrap.commands.daemon._read_config", return_value={
             "owrap_runner_enabled": False,
             "owrap_context_manager_enabled": True,
             "daemon_interval_s": 0.01,
         }), \
         patch("owrap.commands.context_manager.CtxWorkerRunner", MagicMock()), \
         patch("owrap.commands.daemon.time.sleep", side_effect=sleep_fn):
        with pytest.raises(_StopLoop):
            DaemonRunner(MagicMock()).run()

    # No minimum protected once the runner itself is disabled.
    mock_shutdown_idle.assert_called_with(idle_s=300.0, min_n=0)


def test_daemon_cleans_pid_file_on_exit(tmp_path):
    from owrap.commands.daemon import DaemonRunner

    pid_file = tmp_path / ".owrap" / "daemon.pid"
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    sleep_fn, _ = _stop_after(1)

    with patch("owrap.commands.daemon.get_pool", return_value=[]), \
         patch("owrap.commands.daemon._read_config", return_value={
             "daemon_interval_s": 0.01,
             "owrap_context_manager_enabled": False,
         }), \
         patch("owrap.commands.daemon.time.sleep", side_effect=sleep_fn):
        with pytest.raises(_StopLoop):
            DaemonRunner(MagicMock()).run()

    assert not pid_file.exists()


# Context manager background trigger

def test_daemon_triggers_ctx_check_once_interval_elapses(tmp_path):
    import threading

    sleep_fn, calls = _stop_after(1)
    mock_worker_cls = MagicMock()

    with patch("owrap.commands.daemon.get_pool", return_value=[]), \
         patch("owrap.commands.context_manager.CtxWorkerRunner", mock_worker_cls), \
         patch("owrap.commands.daemon._read_config", return_value={
             "owrap_context_manager_enabled": True,
             "daemon_interval_s": 0.01,
             "ctx_check_interval_s": 0,
         }), \
         patch("owrap.commands.daemon.time.sleep", side_effect=sleep_fn):
        from owrap.commands.daemon import DaemonRunner
        with pytest.raises(_StopLoop):
            DaemonRunner(MagicMock()).run()

    # Spawned on a background thread — give it a moment to actually run.
    for t in threading.enumerate():
        if t.name != threading.main_thread().name:
            t.join(timeout=1)
    mock_worker_cls.assert_called_once()
    mock_worker_cls.return_value.check_all_attached.assert_called_once()


def test_daemon_does_not_recheck_before_interval_elapses(tmp_path):
    sleep_fn, calls = _stop_after(5)
    mock_worker_cls = MagicMock()

    with patch("owrap.commands.daemon.get_pool", return_value=[]), \
         patch("owrap.commands.context_manager.CtxWorkerRunner", mock_worker_cls), \
         patch("owrap.commands.daemon._read_config", return_value={
             "owrap_context_manager_enabled": True,
             "daemon_interval_s": 0.01,
             "ctx_check_interval_s": 300,
         }), \
         patch("owrap.commands.daemon.time.sleep", side_effect=sleep_fn):
        from owrap.commands.daemon import DaemonRunner
        with pytest.raises(_StopLoop):
            DaemonRunner(MagicMock()).run()

    # First tick fires once; a 300s interval means no second fire yet.
    assert mock_worker_cls.call_count == 1
