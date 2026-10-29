"""
The daemon pid file alone isn't a reliable mutual-exclusion guard --
`flock` isn't trustworthy on every filesystem, so two near-simultaneous
spawns can both "win" and leave an orphan running forever. The daemon
registry (daemons.json) is the actual source of truth `_kill_other_daemons`
uses to find and clean up every spawned daemon, not just the one the pid
file happens to name -- confirming it actually prunes dead entries and
kills live ones needs a real run, not a read of the code.
"""
import os
import subprocess
import sys

from owrap.kind.run import daemon as daemon_module


def _spawn_sleeper():
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    return proc


def test_register_and_list_round_trips(monkeypatch, tmp_path):
    monkeypatch.setattr(daemon_module, "DAEMON_LOCK_FILE", tmp_path / "daemon.lock")
    monkeypatch.setattr(daemon_module, "DAEMON_PID_FILE", tmp_path / "daemon.pid")
    monkeypatch.setattr(daemon_module, "DAEMON_REGISTRY_FILE", tmp_path / "daemons.json")

    daemon_module._register_daemon(os.getpid())

    assert daemon_module._registered_daemon_pids() == [os.getpid()]


def test_registered_daemon_pids_prunes_dead_entries(monkeypatch, tmp_path):
    monkeypatch.setattr(daemon_module, "DAEMON_LOCK_FILE", tmp_path / "daemon.lock")
    monkeypatch.setattr(daemon_module, "DAEMON_PID_FILE", tmp_path / "daemon.pid")
    registry_file = tmp_path / "daemons.json"
    monkeypatch.setattr(daemon_module, "DAEMON_REGISTRY_FILE", registry_file)

    proc = _spawn_sleeper()
    daemon_module._register_daemon(proc.pid)
    # Never a real pid
    daemon_module._register_daemon(999999999)

    alive = daemon_module._registered_daemon_pids()

    assert alive == [proc.pid]
    assert "999999999" not in daemon_module._read_registry()
    proc.terminate()
    proc.wait(timeout=5)


def test_kill_other_daemons_kills_everyone_but_keep_pid(monkeypatch, tmp_path):
    monkeypatch.setattr(daemon_module, "DAEMON_LOCK_FILE", tmp_path / "daemon.lock")
    monkeypatch.setattr(daemon_module, "DAEMON_PID_FILE", tmp_path / "daemon.pid")
    monkeypatch.setattr(daemon_module, "DAEMON_REGISTRY_FILE", tmp_path / "daemons.json")

    stray1, stray2 = _spawn_sleeper(), _spawn_sleeper()
    daemon_module._register_daemon(stray1.pid)
    daemon_module._register_daemon(stray2.pid)
    daemon_module._register_daemon(os.getpid())

    daemon_module._kill_other_daemons(keep_pid=os.getpid())

    # Reap first -- an unreaped child looks alive to os.kill(pid, 0).
    stray1.wait(timeout=5)
    stray2.wait(timeout=5)
    assert daemon_module._registered_daemon_pids() == [os.getpid()]


def test_unregister_daemon_removes_only_its_own_entry(monkeypatch, tmp_path):
    monkeypatch.setattr(daemon_module, "DAEMON_LOCK_FILE", tmp_path / "daemon.lock")
    monkeypatch.setattr(daemon_module, "DAEMON_PID_FILE", tmp_path / "daemon.pid")
    monkeypatch.setattr(daemon_module, "DAEMON_REGISTRY_FILE", tmp_path / "daemons.json")

    daemon_module._register_daemon(os.getpid())
    daemon_module._register_daemon(12345)

    daemon_module._unregister_daemon(os.getpid())

    registry = daemon_module._read_registry()
    assert str(os.getpid()) not in registry
    assert "12345" in registry
