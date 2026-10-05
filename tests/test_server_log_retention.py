import json
import os
import time

from owrap.utils.log.retention import prune_server_logs


def test_prune_server_logs_keeps_active_and_recent(tmp_path):
    home = tmp_path / "home"
    log_dir = home / "logs"
    runtime_dir = home / "runtime"
    log_dir.mkdir(parents=True)
    runtime_dir.mkdir()
    now = time.time()

    active_pid = os.getpid()
    (runtime_dir / "manager.json").write_text(json.dumps({"pid": active_pid}))
    active_log = log_dir / f"owrap_{active_pid}.log"
    active_log.write_text("active")
    os.utime(active_log, (now - 1000, now - 1000))
    for index in range(15):
        path = log_dir / f"owrap_{100000 + index}.log"
        path.write_text(str(index))
        modified = now - 100 + index
        os.utime(path, (modified, modified))

    recent_start = log_dir / "owrap_start_recent.log"
    recent_start.write_text("starting")
    old_start = home / "owrap_start_old.log"
    old_start.write_text("failed")
    os.utime(old_start, (now - 1000, now - 1000))
    unrelated = log_dir / "owrap_new.log"
    unrelated.write_text("keep")

    prune_server_logs(home, log_dir)

    retained = list(log_dir.glob("owrap_[0-9]*.log"))
    assert len(retained) == 9
    assert active_log.exists()
    assert recent_start.exists()
    assert unrelated.exists()
    assert not old_start.exists()
