import json

import pytest

from owrap.commands.project import ProjectRunner
from owrap.utils.session import resolver


@pytest.fixture
def project_scope(tmp_path, monkeypatch):
    root = tmp_path / "records"
    project = root / "projects" / "demo"
    repository = root / "repositories" / "code"
    sessions = tmp_path / "sessions"
    project.mkdir(parents=True)
    repository.mkdir(parents=True)
    sessions.mkdir(exist_ok=True)
    (project / "demo.yaml").write_text(
        "schema_version: 1\nkind: project\nid: demo\n"
        "main: main.md\nrepositories: [code]\nsubprojects:\n"
        "  worker:\n    kind: regular\n    file: worker.md\n"
        "    parent: main\n"
        "  old:\n    kind: regular\n    file: old.md\n"
        "    parent: main\n    archived: true\n"
    )
    (project / "main.md").write_text("# Demo\n\n## Goals\n")
    (project / "worker.md").write_text("# Worker\n\n## Goals\n")
    (project / "old.md").write_text("# Old\n\n## Goals\n")
    (repository / "code.yaml").write_text(
        "schema_version: 1\nkind: repository\nid: code\n"
        "main: memory.md\ncheckout: /tmp/code\n"
    )
    (repository / "memory.md").write_text("# Code\n")
    session_path = sessions / "abc123" / ".session"
    session_path.parent.mkdir()
    session_path.write_text(
        "session_id=abc123\ntarget_kind=project\nproject_id=demo\n"
        "subproject_id=worker\nworkspace=test\nrepositories=[\"code\"]\n"
    )
    monkeypatch.setenv("SESSION_ID", "abc123")
    monkeypatch.setattr(resolver, "SESSIONS_DIR", sessions)
    monkeypatch.setattr(
        "owrap.commands.project.resolve", resolver.resolve,
    )
    monkeypatch.setattr(
        "owrap.commands.project.set_session_identity",
        resolver.set_session_identity,
    )
    monkeypatch.setattr(
        "owrap.utils.memory.records.get_workspace_config",
        lambda _: {"docs_root": str(root)},
    )
    return project, session_path


def test_main_selects_project_root(project_scope, capsys):
    _, session_path = project_scope

    ProjectRunner().main()

    data = resolver._parse(session_path)
    assert data["subproject_id"] == ""
    assert json.loads(data["repositories"]) == ["code"]
    assert capsys.readouterr().out.strip() == "Project: demo/main"


def test_sub_selects_existing_subproject(project_scope, capsys):
    _, session_path = project_scope

    ProjectRunner().sub("worker")

    assert resolver._parse(session_path)["subproject_id"] == "worker"
    assert capsys.readouterr().out.strip() == "Subproject: demo/worker"


def test_sub_suggests_close_name_without_creating(project_scope):
    project, _ = project_scope

    with pytest.raises(ValueError, match="Did you mean 'worker'"):
        ProjectRunner().sub("worket")

    assert not (project / "worket.md").exists()
    assert "worket:" not in (project / "demo.yaml").read_text()


def test_sub_force_creates_close_name_and_selects_it(project_scope, capsys):
    project, session_path = project_scope

    ProjectRunner().sub("worket", force=True)

    assert resolver._parse(session_path)["subproject_id"] == "worket"
    assert (project / "worket.md").is_file()
    assert "parent: main" in (project / "demo.yaml").read_text()
    assert capsys.readouterr().out.strip() == (
        "Created and selected: demo/worket"
    )


def test_sub_creates_distinct_name_without_force(project_scope):
    project, session_path = project_scope

    ProjectRunner().sub("reports")

    assert resolver._parse(session_path)["subproject_id"] == "reports"
    assert (project / "reports.md").is_file()


def test_subs_lists_current_and_archived(project_scope, capsys):
    ProjectRunner().subs()

    output = capsys.readouterr().out
    assert "Subprojects for demo:" in output
    assert "* worker" in output
    assert "  old [archived]" in output


def test_project_commands_require_active_project(project_scope, monkeypatch):
    _, session_path = project_scope
    monkeypatch.delenv("SESSION_ID")

    with pytest.raises(ValueError, match="no active session"):
        ProjectRunner().subs()

    monkeypatch.setenv("SESSION_ID", "abc123")
    session_path.write_text(
        "session_id=abc123\ntarget_kind=repository\nrepository_id=code\n"
    )
    with pytest.raises(ValueError, match="does not target a project"):
        ProjectRunner().main()
