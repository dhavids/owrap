from unittest.mock import patch

import pytest


def test_get_resolves_codex_session_pointer(tmp_path, monkeypatch):
    from owrap.commands.get import GetRunner

    pointer = tmp_path / "sessions" / "by_codex_session_id" / "codex-123"
    pointer.parent.mkdir(parents=True)
    pointer.write_text("abc123")
    monkeypatch.setenv("CODEX_SESSION_ID", "codex-123")
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.delenv("SESSION_ID", raising=False)
    monkeypatch.setattr("owrap.commands.get.RUNTIME_HOME", tmp_path)

    assert GetRunner()._resolve_session_id(None) == "abc123"


@pytest.fixture
def get_runner(tmp_path):
    from owrap.commands.get import GetRunner
    return GetRunner()


@pytest.fixture
def fake_owrap(tmp_path):
    """
    Set up a private runtime home and session files.
    """
    sessions = tmp_path / "sessions"
    sessions.mkdir(exist_ok=True)
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

    sess = tmp_path / "sessions" / "abc123"
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
    with patch("owrap.commands.get.RUNTIME_HOME", fake_owrap), \
         patch.dict("os.environ", {"SESSION_ID": ""}, clear=True), \
         patch("os.environ", {}):
        get_runner.run("plan", session_id="abc123")
    captured = capsys.readouterr()
    assert "# plan:" in captured.out
    assert "Step 1: do something" in captured.out


def test_get_self_without_session(get_runner, tmp_path, capsys):
    self_path = tmp_path / "self.md"
    self_path.write_text("# Staged reference\n")
    with patch("owrap.commands.get.get_self_path", return_value=self_path):
        get_runner.run("self")
    captured = capsys.readouterr()
    assert f"# self: {self_path}" in captured.out
    assert "# Staged reference" in captured.out


def test_get_plan_empty(get_runner, fake_owrap, capsys):
    empty_plan = fake_owrap / "sessions" / "abc123" / "exec" / "plan.md"
    empty_plan.write_text("\n")
    with patch("owrap.commands.get.RUNTIME_HOME", fake_owrap), \
         patch.dict("os.environ", {}, clear=True):
        get_runner.run("plan", session_id="abc123")
    captured = capsys.readouterr()
    assert "Plan is empty" in captured.out


def test_get_context_missing(get_runner, fake_owrap, capsys):
    ctx_file = fake_owrap / "sessions" / "abc123" / "context.md"
    ctx_file.unlink()
    with patch("owrap.commands.get.RUNTIME_HOME", fake_owrap), \
         patch.dict("os.environ", {}, clear=True):
        with pytest.raises(SystemExit):
            get_runner.run("context", session_id="abc123")
    captured = capsys.readouterr()
    assert "No context file" in captured.out


def test_get_session(get_runner, fake_owrap, capsys):
    with patch("owrap.commands.get.RUNTIME_HOME", fake_owrap), \
         patch.dict("os.environ", {}, clear=True):
        get_runner.run("session", session_id="abc123")
    captured = capsys.readouterr()
    assert "# session:" in captured.out
    assert "abc123" in captured.out
    assert "mytest" in captured.out
    assert "foo" in captured.out


def test_get_memory_no_target(get_runner, fake_owrap, capsys):
    sf = fake_owrap / "sessions" / "abc123.session"
    sf.write_text("session_id=abc123\nworkspace=fakews\n")
    with patch("owrap.commands.get.RUNTIME_HOME", fake_owrap), \
         patch.dict("os.environ", {}, clear=True):
        with pytest.raises(SystemExit):
            get_runner.run("memory", session_id="abc123")
    captured = capsys.readouterr()
    assert "No project/repository target configured" in captured.out


def _project_session(tmp_path, monkeypatch):
    """
    A target_kind=project session with a linked repository, for exercising
    the canonical memory/project read path.
    """
    root = tmp_path / "research"
    project = root / "projects" / "mytest"
    repo = root / "repositories" / "myrepo"
    project.mkdir(parents=True)
    repo.mkdir(parents=True)
    (project / "mytest.yaml").write_text(
        "schema_version: 1\nkind: project\nid: mytest\n"
        "main: main.md\nrepositories: [myrepo]\nsubprojects: {}\n"
    )
    (project / "main.md").write_text("# mytest\n\n## Overview\n\nOverview text\n")
    (repo / "myrepo.yaml").write_text(
        "schema_version: 1\nkind: repository\nid: myrepo\n"
        "main: memory.md\ncheckout: /tmp/myrepo\n"
    )
    (repo / "memory.md").write_text("# Architecture\n\nline1\nline2\n")
    sf = tmp_path / "sessions" / "abc123.session"
    sf.write_text(
        "session_id=abc123\ntarget_kind=project\nproject_id=mytest\n"
        'workspace=fakews\nrepositories=["myrepo"]\n'
    )
    monkeypatch.setattr(
        "owrap.utils.memory.records.get_workspace_config",
        lambda workspace: {"research_root": str(root)},
    )
    return project, repo


def test_get_memory_reads_linked_repository(
    get_runner, fake_owrap, monkeypatch, capsys,
):
    _project_session(fake_owrap, monkeypatch)
    with patch("owrap.commands.get.RUNTIME_HOME", fake_owrap), \
         patch.dict("os.environ", {}, clear=True):
        get_runner.run("memory", session_id="abc123")
    captured = capsys.readouterr()
    assert "# memory:" in captured.out
    assert "line1" in captured.out
    assert "line2" in captured.out


def test_get_project_missing(get_runner, fake_owrap, monkeypatch, capsys):
    project, _ = _project_session(fake_owrap, monkeypatch)
    (project / "main.md").unlink()
    with patch("owrap.commands.get.RUNTIME_HOME", fake_owrap), \
         patch.dict("os.environ", {}, clear=True):
        with pytest.raises(SystemExit):
            get_runner.run("project", session_id="abc123")
    captured = capsys.readouterr()
    assert "Record Markdown not found" in captured.out


def test_session_resolution_env(get_runner, fake_owrap, capsys):
    with patch("owrap.commands.get.RUNTIME_HOME", fake_owrap), \
         patch.dict("os.environ", {"SESSION_ID": "abc123"}, clear=True):
        get_runner.run("session")
    captured = capsys.readouterr()
    assert "abc123" in captured.out


def test_session_resolution_by_ccsid(get_runner, fake_owrap, capsys):
    by_ccsid = fake_owrap / "sessions" / "by_ccsid"
    by_ccsid.mkdir()
    by_ccsid.joinpath("ccc-111").write_text("abc123")
    with patch("owrap.commands.get.RUNTIME_HOME", fake_owrap), \
         patch.dict("os.environ", {"SESSION_ID": "", "CLAUDE_CODE_SESSION_ID": "ccc-111"}, clear=True):
        get_runner.run("session")
    captured = capsys.readouterr()
    assert "abc123" in captured.out


def test_unknown_what(get_runner, fake_owrap, capsys):
    with patch("owrap.commands.get.RUNTIME_HOME", fake_owrap), \
         patch.dict("os.environ", {}, clear=True):
        with pytest.raises(SystemExit):
            get_runner.run("bogus", session_id="abc123")
    captured = capsys.readouterr()
    assert "Usage:" in captured.out


def test_get_area(tmp_path, monkeypatch, capsys):
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    sid = "testsid"
    sf = sessions_dir / f"{sid}.session"
    sf.write_text("session_id=testsid\nresearch=myresearch\narea=main\nworkspace=marl\n")
    monkeypatch.setenv("SESSION_ID", sid)
    monkeypatch.setattr("owrap.commands.get.RUNTIME_HOME", tmp_path)
    from owrap.commands.get import GetRunner
    GetRunner().run("area")
    out = capsys.readouterr().out.strip()
    assert out == "main"


def test_get_research(tmp_path, monkeypatch, capsys):
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    sid = "testsid"
    sf = sessions_dir / f"{sid}.session"
    sf.write_text("session_id=testsid\nresearch=myresearch\narea=main\nworkspace=marl\n")
    monkeypatch.setenv("SESSION_ID", sid)
    monkeypatch.setattr("owrap.commands.get.RUNTIME_HOME", tmp_path)
    from owrap.commands.get import GetRunner
    GetRunner().run("research")
    out = capsys.readouterr().out.strip()
    assert out == "myresearch"


def test_get_config(tmp_path, monkeypatch, capsys):
    import json as _json
    sessions_dir = tmp_path / "sessions"
    configs_dir = tmp_path / "configs"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    configs_dir.mkdir(parents=True)
    sid = "testsid"
    sf = sessions_dir / f"{sid}.session"
    sf.write_text("session_id=testsid\nresearch=myresearch\narea=main\nworkspace=marl\n")
    cfg = {"research_root": "/some/path", "runner_use_oread": True}
    (configs_dir / "marl.json").write_text(_json.dumps(cfg))
    monkeypatch.setenv("SESSION_ID", sid)
    monkeypatch.setattr("owrap.commands.get.RUNTIME_HOME", tmp_path)
    from owrap.commands.get import GetRunner
    GetRunner().run("config")
    out = capsys.readouterr().out
    assert "research_root" in out
    assert "/some/path" in out


def test_get_agent_with_content(tmp_path, monkeypatch, capsys):
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    sid = "testsid"
    sf = sessions_dir / f"{sid}.session"
    sf.write_text("session_id=testsid\nresearch=myresearch\narea=main\nworkspace=marl\n")
    agents_dir = tmp_path / "sessions" / sid / "agents"
    agents_dir.mkdir(parents=True)
    log_file = agents_dir / "output.log"
    log_file.write_text("[a:test1]\ninput: test task\nlog: /path/to/log\nsummary: found nothing\n---\n\n")
    monkeypatch.setenv("SESSION_ID", sid)
    monkeypatch.setattr("owrap.commands.get.RUNTIME_HOME", tmp_path)
    from owrap.commands.get import GetRunner
    GetRunner().run("agents")
    out = capsys.readouterr().out
    assert "# agents:" in out
    assert "output.log" in out
    assert "found nothing" in out


def test_get_agent_missing(tmp_path, monkeypatch, capsys):
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    sid = "testsid"
    sf = sessions_dir / f"{sid}.session"
    sf.write_text("session_id=testsid\nresearch=myresearch\narea=main\nworkspace=marl\n")
    monkeypatch.setenv("SESSION_ID", sid)
    monkeypatch.setattr("owrap.commands.get.RUNTIME_HOME", tmp_path)
    from owrap.commands.get import GetRunner
    with pytest.raises(SystemExit) as exc_info:
        GetRunner().run("agents")
    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "No agent output for session testsid" in out
