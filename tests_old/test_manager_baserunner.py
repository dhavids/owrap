import json as _json
import time

import pytest


def _make_manager():
    from owrap.dispatch.manager import Manager
    manager = Manager.__new__(Manager)
    manager.session_id = ""
    manager.research = ""
    manager._t_invocation = time.time()
    manager._t_cmd_start = None
    manager._t_cmd_end = None
    manager._state_file = str(Manager.STATE_FILE)
    manager._log_file = None
    return manager


def _make_runner(manager):
    from owrap_old.base import BaseRunner

    class _Runner(BaseRunner):
        def run(self, args):
            return 0

    return _Runner(manager)


def test_write_sentinel_registers_running_task(tmp_path):
    from owrap.utils.paths import session_ctx_state_path
    manager = _make_manager()
    manager.session_id = "sid10"
    manager.get_server_url = lambda: ""
    runner = _make_runner(manager)

    sentinel_path = runner._write_sentinel("42", "Do the thing", kind="task")

    state = _json.loads(session_ctx_state_path("sid10").read_text())
    entry = state["running"][sentinel_path.name]
    assert entry["title"] == "Do the thing"
    assert entry["kind"] == "task"


def test_complete_sentinel_clears_running_task(tmp_path):
    from owrap.utils.paths import session_ctx_state_path
    manager = _make_manager()
    manager.session_id = "sid11"
    manager.get_server_url = lambda: ""
    runner = _make_runner(manager)

    sentinel_path = runner._write_sentinel("43", "Do another thing", kind="task")
    state = _json.loads(session_ctx_state_path("sid11").read_text())
    assert sentinel_path.name in state["running"]

    runner._complete_sentinel(sentinel_path, rc=0)

    state = _json.loads(session_ctx_state_path("sid11").read_text())
    assert state["running"] == {}
