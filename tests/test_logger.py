import logging
import os
import time
from pathlib import Path


def test_get_logger_creates_file_handler(tmp_path):
    import importlib
    import logging
    log_path = tmp_path / "test.log"

    # Use a unique logger name to avoid handler accumulation across tests
    logger = logging.getLogger(f"owrap_test_{tmp_path.name}")
    logger.handlers.clear()

    from owrap.utils.logger import get_logger
    lg = get_logger(f"owrap_test_{tmp_path.name}", log_path=log_path)
    lg.info("hello")

    assert log_path.exists()
    assert "hello" in log_path.read_text()


def test_prune_old_logs_keeps_max(tmp_path):
    from owrap.utils.logger import _prune_old_logs

    for i in range(15):
        f = tmp_path / f"owrap_{i:03d}.log"
        f.write_text("x")
        os.utime(f, (i, i))

    _prune_old_logs(tmp_path, "owrap_*.log", max_keep=10)

    remaining = list(tmp_path.glob("owrap_*.log"))
    assert len(remaining) == 10
    names = {f.name for f in remaining}
    for i in range(5, 15):
        assert f"owrap_{i:03d}.log" in names


def test_prune_old_logs_noop_under_limit(tmp_path):
    from owrap.utils.logger import _prune_old_logs

    for i in range(5):
        (tmp_path / f"owrap_{i:03d}.log").write_text("x")

    _prune_old_logs(tmp_path, "owrap_*.log", max_keep=10)

    assert len(list(tmp_path.glob("owrap_*.log"))) == 5


def test_get_logger_calls_prune(tmp_path):
    import logging
    from owrap.utils.logger import get_logger

    for i in range(12):
        f = tmp_path / f"owrap_{i:03d}.log"
        f.write_text("x")
        os.utime(f, (i, i))

    log_path = tmp_path / "owrap_new.log"
    logger_name = f"owrap_prune_test_{tmp_path.name}"
    logging.getLogger(logger_name).handlers.clear()

    get_logger(logger_name, log_path=log_path)

    # 12 old + 1 new = 13; prune keeps 10
    assert len(list(tmp_path.glob("owrap_*.log"))) <= 10
