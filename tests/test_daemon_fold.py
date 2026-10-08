from argparse import Namespace

from owrap.runner import _cmd_restart, _cmd_start, _cmd_stop


def test_start_daemon_calls_ensure_daemon(monkeypatch, capsys):
    monkeypatch.setattr("owrap.utils.dispatch.pool._ensure_daemon", lambda: True)
    _cmd_start(Namespace(project_name="daemon"), None, None, False)
    assert "daemon: started" in capsys.readouterr().out


def test_start_daemon_reports_already_running(monkeypatch, capsys):
    monkeypatch.setattr("owrap.utils.dispatch.pool._ensure_daemon", lambda: False)
    _cmd_start(Namespace(project_name="daemon"), None, None, False)
    assert "daemon: already running" in capsys.readouterr().out


def test_stop_daemon_calls_stop_daemon(monkeypatch, capsys):
    monkeypatch.setattr("owrap.utils.dispatch.pool._stop_daemon", lambda: True)
    _cmd_stop(Namespace(session_id=None, target="daemon"), None, None, False)
    assert "daemon: stopped" in capsys.readouterr().out


def test_restart_daemon_calls_restart_daemon(monkeypatch, capsys):
    called = []
    monkeypatch.setattr(
        "owrap.utils.dispatch.pool._restart_daemon", lambda: called.append(True),
    )
    _cmd_restart(Namespace(project_name="daemon"), None, None, False)
    assert called == [True]
    assert "daemon: restarted" in capsys.readouterr().out
