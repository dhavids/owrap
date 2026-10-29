"""
`Self.get("runtime"/"history")` -- ported from the live `owrap get
runtime`/`owrap get history` (`owrap/commands/get.py::run_runtime`/
`run_runtime_history`), closing a real gap: the new `cli.py` never
logged anything to rtlog at all until `cmd.start`/`cmd.end` was added
to `main()`, so there was no record of what commands actually ran.
"""
import json

import pytest

from owrap.kind.op.self import Self


@pytest.fixture
def rtlog_file(tmp_path, monkeypatch):
    path = tmp_path / "runtime.log"
    events = [
        {"ts": "2026-01-01T10:00:00.000", "pid": 1, "sid": "sid1",
         "ev": "cmd.start", "cmd": "session start", "argv": "session start proj"},
        {"ts": "2026-01-01T10:00:01.000", "pid": 1, "sid": "sid1",
         "ev": "cmd.end", "cmd": "session start", "rc": 0, "dur_s": 1.2,
         "result": "session: abc123 project: proj"},
        {"ts": "2026-01-01T10:00:05.000", "pid": 2, "sid": "sid1",
         "ev": "server.spawn", "port": 8080},
        {"ts": "2026-01-01T10:00:10.000", "pid": 3, "sid": "sid2",
         "ev": "cmd.start", "cmd": "task start", "argv": "task start --msg hi"},
        {"ts": "2026-01-01T10:00:12.000", "pid": 3, "sid": "sid2",
         "ev": "cmd.end", "cmd": "task start", "rc": 1, "dur_s": 2.4,
         "error": "project not found: demo"},
    ]
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n")
    monkeypatch.setattr("owrap.kind.op.self.RUNTIME_LOG", path)
    return path


def test_runtime_bare_shows_path_and_every_event(rtlog_file, capsys):
    Self().get("runtime")
    out = capsys.readouterr().out
    assert str(rtlog_file) in out
    assert "cmd.start" in out and "server.spawn" in out and "cmd.end" in out


def test_runtime_grep_filters_to_matching_lines(rtlog_file, capsys):
    Self().get("runtime", grep="server.spawn")
    out = capsys.readouterr().out
    assert "server.spawn" in out
    assert "cmd.start" not in out


def test_runtime_sid_filters_to_that_session(rtlog_file, capsys):
    Self().get("runtime", sid="sid2")
    out = capsys.readouterr().out
    assert "task start" in out
    assert "session start" not in out


def test_runtime_tail_limits_event_count(rtlog_file, capsys):
    Self().get("runtime", tail="1")
    out = capsys.readouterr().out.strip().splitlines()
    # The "log: ..." header line, then one event
    assert len(out) == 2


def test_runtime_missing_file_reports_cleanly(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        "owrap.kind.op.self.RUNTIME_LOG", tmp_path / "missing.log",
    )
    Self().get("runtime")
    out = capsys.readouterr().out
    assert "not found" in out
    assert "no events" in out


def test_history_pairs_cmd_start_and_end_with_argv(rtlog_file, capsys):
    Self().get("history", sid="sid1")
    out = capsys.readouterr().out
    assert "session start" in out
    assert "done(ok)" in out
    assert "argv: session start proj" in out


def test_history_reports_nonzero_rc(rtlog_file, capsys):
    Self().get("history", sid="sid2")
    out = capsys.readouterr().out
    assert "done(rc=1)" in out


def test_history_shows_result_snippet_on_success(rtlog_file, capsys):
    Self().get("history", sid="sid1")
    out = capsys.readouterr().out
    assert "result: session: abc123 project: proj" in out


def test_history_shows_error_snippet_on_failure(rtlog_file, capsys):
    Self().get("history", sid="sid2")
    out = capsys.readouterr().out
    assert "error: project not found: demo" in out


def test_history_respects_count(rtlog_file, capsys):
    Self().get("history", count="1", sid=None)
    out = capsys.readouterr().out
    assert "last 1 of 2" in out


def test_runtime_history_is_an_alias_for_history(rtlog_file, capsys):
    Self().get("runtime", "history", sid="sid1")
    out = capsys.readouterr().out
    assert "session start" in out
    assert "argv:" in out


def test_history_falls_back_to_session_id_env_when_no_explicit_sid(
    rtlog_file, monkeypatch, capsys,
):
    monkeypatch.setenv("SESSION_ID", "sid1")
    Self().get("history")
    out = capsys.readouterr().out
    assert "session start" in out
    assert "task start" not in out


def test_history_no_dispatches_reports_cleanly(tmp_path, monkeypatch, capsys):
    path = tmp_path / "runtime.log"
    path.write_text("")
    monkeypatch.setattr("owrap.kind.op.self.RUNTIME_LOG", path)
    Self().get("history", sid="nope")
    out = capsys.readouterr().out
    assert "No dispatch history for session nope" in out


def test_history_missing_file_reports_cleanly(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        "owrap.kind.op.self.RUNTIME_LOG", tmp_path / "missing.log",
    )
    Self().get("history")
    out = capsys.readouterr().out
    assert "No runtime log yet" in out


def _wire_cli(monkeypatch, cli_module, log_path, **extra_kinds):
    import owrap.utils.log.rtlog as rtlog_module

    monkeypatch.delenv("OWRAP_TEST_MODE", raising=False)
    monkeypatch.setattr(rtlog_module, "RUNTIME_LOG", log_path)
    # _fd is cached across calls; reset it so the new RUNTIME_LOG path takes.
    monkeypatch.setattr(rtlog_module, "_fd", None)

    class _NoopDaemon:
        @staticmethod
        def ensure_daemon():
            pass

    registry = {"daemon": _NoopDaemon, **extra_kinds}
    monkeypatch.setattr(cli_module, "KIND_REGISTRY", registry)
    monkeypatch.setattr(cli_module, "KIND_ALIASES", {})
    monkeypatch.setattr(cli_module, "ACTION_REGISTRY", {})


def test_main_logs_cmd_start_and_end_to_rtlog(monkeypatch, tmp_path):
    import owrap.cli as cli_module

    log_path = tmp_path / "rt.log"
    _wire_cli(monkeypatch, cli_module, log_path, self=Self)
    cli_module.main(["self", "get", "home"])

    events = [json.loads(line) for line in log_path.read_text().splitlines()]
    assert [e["ev"] for e in events] == ["cmd.start", "cmd.end"]
    assert events[0]["cmd"] == "self get"
    assert events[1]["rc"] == 0


def test_main_logs_a_result_snippet_on_success(monkeypatch, tmp_path):
    import owrap.cli as cli_module

    class _ToyKind:
        kind = "toy"

        def ok(self):
            return "wrote 3 goals to the project record"

    log_path = tmp_path / "rt.log"
    _wire_cli(monkeypatch, cli_module, log_path, toy=_ToyKind)
    cli_module.main(["toy", "ok"])

    events = [json.loads(line) for line in log_path.read_text().splitlines()]
    assert events[1]["result"] == "wrote 3 goals to the project record"


def test_main_logs_an_error_snippet_on_failure(monkeypatch, tmp_path):
    import owrap.cli as cli_module

    class _ToyKind:
        kind = "toy"

        def bad(self):
            raise ValueError("project not found: demo")

    log_path = tmp_path / "rt.log"
    _wire_cli(monkeypatch, cli_module, log_path, toy=_ToyKind)
    with pytest.raises(SystemExit):
        cli_module.main(["toy", "bad"])

    events = [json.loads(line) for line in log_path.read_text().splitlines()]
    assert events[1]["rc"] == 2
    assert events[1]["error"] == "project not found: demo"
