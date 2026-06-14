import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def test_read_log_isolation(tmp_path, monkeypatch):
    import owrap.utils.paths as _upaths

    real_read_log = Path("/home/humble/.owrap/docs/sessions/067fcf/read/log.md")
    stored = real_read_log.read_text() if real_read_log.exists() else None

    monkeypatch.setenv("OWRAP_SESSION", "067fcf")

    test_file = tmp_path / "test.txt"
    test_file.write_text("hello")
    with patch.object(sys, "argv", ["oread", "read", "-f", str(test_file)]), \
         patch("owrap.runner._read_config", return_value={"default_workspace": "test"}), \
         patch("owrap.runner.get_workspace_config", return_value={"oread": True}), \
         patch("owrap.commands.read.Terminal") as mock_terminal_cls, \
         patch("owrap.commands.read._pool_active", return_value=False):
        mock_terminal = MagicMock()
        mock_terminal.run.return_value = {"returncode": 0, "stdout": ""}
        mock_terminal_cls.return_value = mock_terminal
        with pytest.raises(SystemExit):
            from owrap.runner import main
            main()

    if stored is None:
        assert not real_read_log.exists(), (
            "Real read log was created when it should not have been"
        )
    else:
        assert real_read_log.read_text() == stored, (
            "Real read log was modified by the test run"
        )

    isolated_log = _upaths.SESSIONS_DIR / "067fcf" / "read" / "log.md"
    assert isolated_log.exists(), f"Isolated read log not found at {isolated_log}"
    content = isolated_log.read_text()
    assert "test.txt" in content, f"Snippet not found in isolated log: {content!r}"


def test_global_read_log_isolation(tmp_path, monkeypatch, isolate_owrap_dirs):
    global_read_log = Path("/home/humble/.owrap/docs/read/log.md")
    stored = global_read_log.read_text() if global_read_log.exists() else None

    monkeypatch.delenv("OWRAP_SESSION", raising=False)

    test_file = tmp_path / "test.txt"
    test_file.write_text("hello")
    with patch.object(sys, "argv", ["oread", "read", "-f", str(test_file)]), \
         patch("owrap.runner._read_config", return_value={"default_workspace": "test"}), \
         patch("owrap.runner.get_workspace_config", return_value={"oread": True}), \
         patch("owrap.commands.read.Terminal") as mock_terminal_cls, \
         patch("owrap.commands.read._pool_active", return_value=False):
        mock_terminal = MagicMock()
        mock_terminal.run.return_value = {"returncode": 0, "stdout": ""}
        mock_terminal_cls.return_value = mock_terminal
        with pytest.raises(SystemExit):
            from owrap.runner import main
            main()

    if stored is None:
        assert not global_read_log.exists(), (
            "Real global read log was created when it should not have been"
        )
    else:
        assert global_read_log.read_text() == stored, (
            "Real global read log was modified by the test run"
        )

    isolated_log = isolate_owrap_dirs["READ_LOG"]
    assert isolated_log.exists(), f"Isolated read log not found at {isolated_log}"
    content = isolated_log.read_text()
    assert "test.txt" in content, f"Snippet not found in isolated log: {content!r}"
