import sys
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def get_runner(tmp_path):
    from owrap.commands.get_cmd import GetRunner
    return GetRunner()


@pytest.fixture
def fake_owrap(tmp_path):
    """Set up fake RUNTIME_HOME with session, plan, input, context, memory, projects files."""
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    session_file = sessions / "abc123.session"
    session_file.write_text(
        "session_id=abc123\n"
        "research=mytest\n"
        "area=foo\n"
        "workspace=fakews\n"
        "last_refresh=2026-06-12T10:00:00\n"
        "started=2026-06-12T09:00:00\n"
    )

    configs = tmp_path / "configs"
    configs.mkdir()
    import json
    configs.joinpath("fakews.json").write_text(json.dumps({
        "research_root": str(tmp_path / "research"),
        "workspace": "/fake/ws",
    }))

    sess = tmp_path / "docs" / "sessions" / "abc123"
    sess.mkdir(parents=True)
    sess.joinpath("exec/plan.md").parent.mkdir(parents=True, exist_ok=True)
    sess.joinpath("exec/plan.md").write_text("## plan\n\nStep 1: do something\n")

    sess.joinpath("run/input.md").parent.mkdir(parents=True, exist_ok=True)
    sess.joinpath("run/input.md").write_text("## Do\n\nTest task\n")

    sess.joinpath("context.md").write_text("## Focus\n\nCurrent focus\n")

    research_dir = tmp_path / "research"
    memory_dir = research_dir / "memory"
    memory_dir.mkdir(parents=True)
    memory_dir.joinpath("mytest.md").write_text(
        "## foo\n\nline1\nline2\n\n## bar\n\nother\n"
    )
    projects_dir = research_dir / "projects"
    projects_dir.mkdir(parents=True)
    projects_dir.joinpath("mytest.md").write_text("## Overview\n\nOverview text\n")

    return tmp_path


def test_get_plan_with_content(get_runner, fake_owrap, capsys):
    with patch("owrap.commands.get_cmd.RUNTIME_HOME", fake_owrap), \
         patch.dict("os.environ", {"SESSION_ID": ""}, clear=True), \
         patch("os.environ", {}):
        get_runner.run("plan", session_id="abc123")
    captured = capsys.readouterr()
    assert "# plan:" in captured.out
    assert "Step 1: do something" in captured.out


def test_get_plan_empty(get_runner, fake_owrap, capsys):
    empty_plan = fake_owrap / "docs" / "sessions" / "abc123" / "exec" / "plan.md"
    empty_plan.write_text("\n")
    with patch("owrap.commands.get_cmd.RUNTIME_HOME", fake_owrap), \
         patch.dict("os.environ", {}, clear=True):
        get_runner.run("plan", session_id="abc123")
    captured = capsys.readouterr()
    assert "Plan is empty" in captured.out


def test_get_context_missing(get_runner, fake_owrap, capsys):
    ctx_file = fake_owrap / "docs" / "sessions" / "abc123" / "context.md"
    ctx_file.unlink()
    with patch("owrap.commands.get_cmd.RUNTIME_HOME", fake_owrap), \
         patch.dict("os.environ", {}, clear=True):
        with pytest.raises(SystemExit):
            get_runner.run("context", session_id="abc123")
    captured = capsys.readouterr()
    assert "No context file" in captured.out


def test_get_session(get_runner, fake_owrap, capsys):
    with patch("owrap.commands.get_cmd.RUNTIME_HOME", fake_owrap), \
         patch.dict("os.environ", {}, clear=True):
        get_runner.run("session", session_id="abc123")
    captured = capsys.readouterr()
    assert "# session:" in captured.out
    assert "abc123" in captured.out
    assert "mytest" in captured.out
    assert "foo" in captured.out


def test_get_memory_no_research(get_runner, fake_owrap, capsys):
    sf = fake_owrap / "sessions" / "abc123.session"
    sf.write_text("session_id=abc123\nworkspace=fakews\n")
    with patch("owrap.commands.get_cmd.RUNTIME_HOME", fake_owrap), \
         patch.dict("os.environ", {}, clear=True):
        with pytest.raises(SystemExit):
            get_runner.run("memory", session_id="abc123")
    captured = capsys.readouterr()
    assert "No research configured" in captured.out


def test_get_memory_with_area(get_runner, fake_owrap, capsys):
    with patch("owrap.commands.get_cmd.RUNTIME_HOME", fake_owrap), \
         patch.dict("os.environ", {}, clear=True):
        get_runner.run("memory", session_id="abc123")
    captured = capsys.readouterr()
    assert "# memory:" in captured.out
    assert "line1" in captured.out
    assert "line2" in captured.out
    assert "## bar" not in captured.out


def test_get_project_missing(get_runner, fake_owrap, capsys):
    proj_file = fake_owrap / "research" / "projects" / "mytest.md"
    proj_file.unlink()
    with patch("owrap.commands.get_cmd.RUNTIME_HOME", fake_owrap), \
         patch.dict("os.environ", {}, clear=True):
        with pytest.raises(SystemExit):
            get_runner.run("project", session_id="abc123")
    captured = capsys.readouterr()
    assert "does not exist" in captured.out


def test_session_resolution_env(get_runner, fake_owrap, capsys):
    with patch("owrap.commands.get_cmd.RUNTIME_HOME", fake_owrap), \
         patch.dict("os.environ", {"SESSION_ID": "abc123"}, clear=True):
        get_runner.run("session")
    captured = capsys.readouterr()
    assert "abc123" in captured.out


def test_session_resolution_by_ccsid(get_runner, fake_owrap, capsys):
    by_ccsid = fake_owrap / "sessions" / "by_ccsid"
    by_ccsid.mkdir()
    by_ccsid.joinpath("ccc-111").write_text("abc123")
    with patch("owrap.commands.get_cmd.RUNTIME_HOME", fake_owrap), \
         patch.dict("os.environ", {"SESSION_ID": "", "CLAUDE_CODE_SESSION_ID": "ccc-111"}, clear=True):
        get_runner.run("session")
    captured = capsys.readouterr()
    assert "abc123" in captured.out


def test_unknown_what(get_runner, fake_owrap, capsys):
    with patch("owrap.commands.get_cmd.RUNTIME_HOME", fake_owrap), \
         patch.dict("os.environ", {}, clear=True):
        with pytest.raises(SystemExit):
            get_runner.run("bogus", session_id="abc123")
    captured = capsys.readouterr()
    assert "Usage:" in captured.out


def test_get_area(tmp_path, monkeypatch, capsys):
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir(parents=True)
    sid = "testsid"
    sf = sessions_dir / f"{sid}.session"
    sf.write_text("session_id=testsid\nresearch=myresearch\narea=main\nworkspace=marl\n")
    monkeypatch.setenv("SESSION_ID", sid)
    monkeypatch.setattr("owrap.commands.get_cmd.RUNTIME_HOME", tmp_path)
    from owrap.commands.get_cmd import GetRunner
    GetRunner().run("area")
    out = capsys.readouterr().out.strip()
    assert out == "main"


def test_get_research(tmp_path, monkeypatch, capsys):
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir(parents=True)
    sid = "testsid"
    sf = sessions_dir / f"{sid}.session"
    sf.write_text("session_id=testsid\nresearch=myresearch\narea=main\nworkspace=marl\n")
    monkeypatch.setenv("SESSION_ID", sid)
    monkeypatch.setattr("owrap.commands.get_cmd.RUNTIME_HOME", tmp_path)
    from owrap.commands.get_cmd import GetRunner
    GetRunner().run("research")
    out = capsys.readouterr().out.strip()
    assert out == "myresearch"


def test_get_config(tmp_path, monkeypatch, capsys):
    import json as _json
    sessions_dir = tmp_path / "sessions"
    configs_dir = tmp_path / "configs"
    sessions_dir.mkdir(parents=True)
    configs_dir.mkdir(parents=True)
    sid = "testsid"
    sf = sessions_dir / f"{sid}.session"
    sf.write_text("session_id=testsid\nresearch=myresearch\narea=main\nworkspace=marl\n")
    cfg = {"research_root": "/some/path", "oread": True}
    (configs_dir / "marl.json").write_text(_json.dumps(cfg))
    monkeypatch.setenv("SESSION_ID", sid)
    monkeypatch.setattr("owrap.commands.get_cmd.RUNTIME_HOME", tmp_path)
    from owrap.commands.get_cmd import GetRunner
    GetRunner().run("config")
    out = capsys.readouterr().out
    assert "research_root" in out
    assert "/some/path" in out
