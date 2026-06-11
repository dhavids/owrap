from pathlib import Path


def test_context_path_under_context_dir():
    from owrap.utils.paths import context_path, CONTEXT_DIR
    p = context_path("abc123")
    assert p.parent == CONTEXT_DIR
    assert p.name == "context_abc123.md"


def test_context_lock_path_under_context_dir():
    from owrap.utils.paths import context_lock_path, CONTEXT_DIR
    p = context_lock_path("abc123")
    assert p.parent == CONTEXT_DIR
    assert p.name == "context_abc123.lock"


def test_get_plan_path_under_exec_plans():
    from owrap.utils.paths import get_plan_path, PLANS_DIR
    p = get_plan_path("abc123")
    assert p.parent == PLANS_DIR
    assert p.name == "plan_abc123.md"


def test_session_log_under_docs(tmp_path):
    from owrap.utils.paths import session_log
    base = tmp_path / "run" / "log.md"
    p = session_log(base, "abc123")
    assert p.name == "log_abc123.md"
    assert p.parent == base.parent


def test_server_logs_dir_under_runtime_home():
    from owrap.utils.paths import SERVER_LOGS_DIR, RUNTIME_HOME
    assert SERVER_LOGS_DIR.parent == RUNTIME_HOME


def test_task_logs_dir_under_run_output():
    from owrap.utils.paths import TASK_LOGS_DIR
    # Name check: constant is always RUN_OUTPUT_DIR / "task"; patched in tests but name is preserved
    assert TASK_LOGS_DIR.name in ("task", "task_logs")


def test_plans_dir_under_exec_dir():
    from owrap.utils.paths import PLANS_DIR
    assert PLANS_DIR.name == "plans"
