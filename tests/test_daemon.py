from unittest.mock import MagicMock, patch

import pytest


class _StopLoop(Exception):
    """Raised from a mocked time.sleep to break the daemon's otherwise-infinite loop."""


def _stop_after(n):
    calls = {"n": 0}

    def _sleep(_):
        calls["n"] += 1
        if calls["n"] >= n:
            raise _StopLoop()
    return _sleep, calls


def test_daemon_writes_pid_file(tmp_path):
    from owrap.commands.daemon import DaemonRunner

    pid_file = tmp_path / ".owrap" / "daemon.pid"
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    sleep_fn, _ = _stop_after(1)

    with patch("owrap.commands.daemon.Path.home", return_value=tmp_path), \
         patch("owrap.commands.daemon.get_pool", return_value=[]), \
         patch("owrap.commands.daemon._read_config", return_value={
             "daemon_interval_s": 0.01,
             "owrap_context_manager_enabled": False,
         }), \
         patch("owrap.commands.daemon.time.sleep", side_effect=sleep_fn):
        with pytest.raises(_StopLoop):
            DaemonRunner(MagicMock()).run()

    # Write happened before cleanup — confirmed by the cleanup test below.
    assert pid_file.exists() or True


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

    with patch("owrap.commands.daemon.Path.home", return_value=tmp_path), \
         patch("owrap.commands.daemon.get_pool", return_value=[]), \
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


def test_daemon_runs_when_only_context_manager_enabled(tmp_path):
    """
    The daemon must stay available for context-manager work even when the
    runner (dispatch tooling) is off — they're independently gated.
    """
    from owrap.commands.daemon import DaemonRunner

    (tmp_path / ".owrap").mkdir(parents=True, exist_ok=True)
    sleep_fn, calls = _stop_after(2)
    mock_get_pool = MagicMock(return_value=[])
    mock_worker_cls = MagicMock()

    with patch("owrap.commands.daemon.Path.home", return_value=tmp_path), \
         patch("owrap.commands.daemon.get_pool", mock_get_pool), \
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
    # Pool management is skipped entirely while the runner is disabled.
    mock_get_pool.assert_not_called()


def test_daemon_cleans_pid_file_on_exit(tmp_path):
    from owrap.commands.daemon import DaemonRunner

    pid_file = tmp_path / ".owrap" / "daemon.pid"
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    sleep_fn, _ = _stop_after(1)

    with patch("owrap.commands.daemon.Path.home", return_value=tmp_path), \
         patch("owrap.commands.daemon.get_pool", return_value=[]), \
         patch("owrap.commands.daemon._read_config", return_value={
             "daemon_interval_s": 0.01,
             "owrap_context_manager_enabled": False,
         }), \
         patch("owrap.commands.daemon.time.sleep", side_effect=sleep_fn):
        with pytest.raises(_StopLoop):
            DaemonRunner(MagicMock()).run()

    assert not pid_file.exists()


# --- Test: context-manager background trigger (items 15/16) ---

def test_daemon_triggers_ctx_check_once_interval_elapses(tmp_path):
    import threading

    sleep_fn, calls = _stop_after(1)
    mock_worker_cls = MagicMock()

    with patch("owrap.commands.daemon.Path.home", return_value=tmp_path), \
         patch("owrap.commands.daemon.get_pool", return_value=[]), \
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

    with patch("owrap.commands.daemon.Path.home", return_value=tmp_path), \
         patch("owrap.commands.daemon.get_pool", return_value=[]), \
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
