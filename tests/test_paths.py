import os
import sys
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest


def test_pytest_state_and_log_stay_in_dev_files():
    from owrap.utils.paths import OWRAP_HOME, RUNTIME_LOG, POOL_FILE, _read_config

    dev_root = Path(__file__).resolve().parents[1]
    assert OWRAP_HOME.is_relative_to(dev_root / "files" / "test-runs")
    assert RUNTIME_LOG == OWRAP_HOME / "runtime" / "runtime.log"
    assert POOL_FILE == OWRAP_HOME / "runtime" / "pool.json"
    assert _read_config()["server_port_base"] == 15096


def test_context_path_under_context_dir():
    from owrap.utils.paths import context_path, SESSIONS_DIR
    p = context_path("abc123")
    assert p == SESSIONS_DIR / "abc123" / "context.md"


def test_session_and_fallback_paths_share_session_root(isolate_owrap_dirs):
    from owrap.utils.paths import (
        EXEC_LOG, FALLBACK_DIR, READ_LOG, RUN_DIR, SESSIONS_DIR,
    )

    assert SESSIONS_DIR == isolate_owrap_dirs["SESSIONS_DIR"]
    assert FALLBACK_DIR == SESSIONS_DIR / "f"
    assert RUN_DIR == FALLBACK_DIR / "run"
    assert EXEC_LOG == FALLBACK_DIR / "exec" / "log.md"
    assert READ_LOG == FALLBACK_DIR / "read" / "log.md"


def test_context_lock_path_under_context_dir():
    from owrap.utils.paths import context_lock_path, SESSIONS_DIR
    p = context_lock_path("abc123")
    assert p == SESSIONS_DIR / "abc123" / "context.lock"


def test_context_jobs_share_session_directory():
    from owrap.utils.paths import SESSIONS_DIR, session_ctx_jobs_dir

    assert session_ctx_jobs_dir("abc123") == (
        SESSIONS_DIR / "abc123" / "ctx" / "jobs"
    )


def test_context_counters_stay_in_session_window():
    from owrap.utils.paths import SESSIONS_DIR, session_ctx_counters_path

    assert session_ctx_counters_path("abc123", "codex-1") == (
        SESSIONS_DIR / "abc123" / "ctx" / "windows" / "codex-1"
        / "counters.json"
    )


def test_get_plan_path_under_exec_plans():
    from owrap.utils.paths import get_plan_path, SESSIONS_DIR
    p = get_plan_path("abc123")
    assert p == SESSIONS_DIR / "abc123" / "exec" / "plan.md"


def test_session_log_under_docs(tmp_path):
    from owrap.utils.paths import session_log, SESSIONS_DIR
    base = tmp_path / "run" / "log.md"
    p = session_log(base, "abc123")
    assert p == SESSIONS_DIR / "abc123" / base.parent.name / base.name


def test_server_logs_dir_under_runtime_home():
    from owrap.utils.paths import SERVER_LOGS_DIR, RUNTIME_HOME
    assert SERVER_LOGS_DIR.parent == RUNTIME_HOME


def test_resolve_general_instruction_path_returns_claude_md(tmp_path):
    from owrap.utils.paths import resolve_general_instruction_path
    with patch("owrap.utils.paths._read_config", return_value={"default_workspace": "x"}):
        with patch("owrap.utils.paths.get_workspace_config", return_value={"workspace": str(tmp_path)}):
            (tmp_path / "CLAUDE.md").write_text("# test")
            (tmp_path / "AGENTS.md").write_text("# test")
            with patch("owrap.utils.session.resolver._parse", return_value={"claude_session_id": "abc123"}):
                with patch("owrap.utils.session.resolver.session_file", return_value=tmp_path / "sid.session"):
                    result = resolve_general_instruction_path("test123")
                    assert result is not None
                    assert result.name == "CLAUDE.md"


def test_resolve_general_instruction_path_returns_agents_md(tmp_path):
    from owrap.utils.paths import resolve_general_instruction_path
    with patch("owrap.utils.paths._read_config", return_value={"default_workspace": "x"}):
        with patch("owrap.utils.paths.get_workspace_config", return_value={"workspace": str(tmp_path)}):
            (tmp_path / "AGENTS.md").write_text("# test")
            with patch("owrap.utils.session.resolver._parse", return_value={}):
                with patch("owrap.utils.session.resolver.session_file", return_value=tmp_path / "sid.session"):
                    result = resolve_general_instruction_path("test123")
                    assert result is not None
                    assert result.name == "AGENTS.md"


def test_format_failure_pointer_self_target(tmp_path):
    from owrap.utils.paths import format_failure_pointer
    with patch("owrap.utils.paths.get_self_path", return_value=tmp_path / "self.md"):
        (tmp_path / "self.md").write_text("## Update Context\n")
        msg = format_failure_pointer("TIMED_OUT", "test123")
        assert "#DO NOW" in msg
        assert "TIMED_OUT" in msg
        assert "Command Reference — timeout/retry" in msg
        assert str(tmp_path / "self.md") in msg


def test_format_failure_pointer_instruction_target(tmp_path):
    from owrap.utils.paths import format_failure_pointer
    with patch("owrap.utils.paths.resolve_general_instruction_path", return_value=tmp_path / "AGENTS.md"):
        (tmp_path / "AGENTS.md").write_text("## Runner Tooling\n")
        msg = format_failure_pointer("INPUT_EMPTY", "test123")
        assert "#DO NOW" in msg
        assert "INPUT_EMPTY" in msg
        assert "Runner Tooling — File task" in msg
        assert str(tmp_path / "AGENTS.md") in msg


def test_all_failure_pointers_have_sections():
    from owrap.utils.constants import FAILURE_POINTERS
    for code, (target, section) in FAILURE_POINTERS.items():
        assert target in ("self", "instruction")
        assert isinstance(section, str) and len(section) > 0


def test_format_failure_pointer_returns_donow_for_all_codes():
    from owrap.utils.constants import FAILURE_POINTERS
    from owrap.utils.paths import format_failure_pointer
    for code in FAILURE_POINTERS:
        with patch("owrap.utils.paths.get_self_path", return_value=Path("/tmp/fake_self.md")):
            with patch("owrap.utils.paths.resolve_general_instruction_path", return_value=Path("/tmp/fake_instr.md")):
                msg = format_failure_pointer(code, "test123")
                assert "#DO NOW" in msg
                assert code in msg


def test_legacy_dirs_not_created_on_import(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    env = {**os.environ, "HOME": str(home)}
    subprocess.run(
        [sys.executable, "-c", "import owrap.utils.paths"],
        env=env,
        check=True,
    )
    assert not (home / ".owrap" / "docs" / "context").exists()
    assert not (home / ".owrap" / "docs" / "exec" / "plans").exists()
    assert not (home / ".owrap" / "docs" / "run" / "output" / "msg").exists()
    assert not (home / ".owrap" / "docs" / "run" / "output" / "task").exists()


@pytest.mark.parametrize("config,expected", [
    (
        {
            "context_manager_model": "custom/model",
            "runner_model": "runner/model",
            "context_fallback_model": "fallback/model",
        },
        "custom/model",
    ),
    (
        {"runner_model": "runner/model", "context_fallback_model": "fallback/model"},
        "runner/model",
    ),
    ({"context_fallback_model": "fallback/model"}, "fallback/model"),
], ids=[
    "prefers_key", "falls_back_to_runner_model",
    "falls_back_to_context_fallback_model",
])
def test_get_maintenance_model(config, expected):
    from owrap.utils.paths import get_maintenance_model
    assert get_maintenance_model(config) == expected


def test_get_maintenance_model_none_when_nothing_configured():
    from owrap.utils.paths import get_maintenance_model
    assert get_maintenance_model({}) is None


def test_get_model_chain_orders_and_dedupes():
    from owrap.utils.paths import get_model_chain
    chain = get_model_chain({
        "context_manager_model": "custom/model",
        "runner_model": "custom/model",
        "context_fallback_model": "fallback/model",
    })
    assert chain == ["custom/model", "fallback/model"]


def test_get_model_chain_empty_when_nothing_configured():
    from owrap.utils.paths import get_model_chain
    assert get_model_chain({}) == []
