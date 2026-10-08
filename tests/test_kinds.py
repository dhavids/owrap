import pytest

from owrap.commands.kinds import KIND_REGISTRY
from owrap.utils.actions import dispatch
from owrap.utils.session import resolver


@pytest.fixture
def kinds_scope(tmp_path, monkeypatch):
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
    )
    (project / "main.md").write_text("# Demo\n\n## Goals\n")
    (project / "worker.md").write_text(
        "# Worker\n\n## Overview\n\nPart of [demo](main.md).\n\n## Goals\n"
    )
    (repository / "code.yaml").write_text(
        "schema_version: 1\nkind: repository\nid: code\n"
        "main: memory.md\ncheckout: /tmp/code\n"
    )
    (repository / "memory.md").write_text("# Code\n")

    # An unattached project/subproject/repository, for clean remove tests.
    spare_project = root / "projects" / "spare"
    spare_repo = root / "repositories" / "extra"
    spare_project.mkdir(parents=True)
    spare_repo.mkdir(parents=True)
    (spare_project / "spare.yaml").write_text(
        "schema_version: 1\nkind: project\nid: spare\n"
        "main: main.md\nrepositories: []\nsubprojects:\n"
        "  loose:\n    kind: regular\n    file: loose.md\n"
        "    parent: main\n"
    )
    (spare_project / "main.md").write_text("# Spare\n\n## Goals\n")
    (spare_project / "loose.md").write_text(
        "# Loose\n\n## Overview\n\nPart of [spare](main.md).\n\n## Goals\n"
    )
    (spare_repo / "extra.yaml").write_text(
        "schema_version: 1\nkind: repository\nid: extra\nmain: memory.md\n"
    )
    (spare_repo / "memory.md").write_text("# Extra\n")

    session_path = sessions / "abc123" / ".session"
    session_path.parent.mkdir()
    session_path.write_text(
        "session_id=abc123\ntarget_kind=project\nproject_id=demo\n"
        "subproject_id=worker\nworkspace=test\nrepositories=[\"code\"]\n"
    )
    monkeypatch.setenv("SESSION_ID", "abc123")
    monkeypatch.setattr(resolver, "SESSIONS_DIR", sessions)
    monkeypatch.setattr("owrap.commands.rename.session_file", resolver.session_file)
    monkeypatch.setattr("owrap.commands.rename.session_files", resolver.session_files)
    monkeypatch.setattr(
        "owrap.utils.memory.records.get_workspace_config",
        lambda _: {"docs_root": str(root)},
    )
    return root


def test_dispatch_update_project(kinds_scope):
    root = kinds_scope
    message = dispatch(KIND_REGISTRY, "project", "update", "demo", "renamed")
    assert message == "Renamed project demo -> renamed"
    assert (root / "projects" / "renamed" / "renamed.yaml").exists()


def test_dispatch_update_repo_alias(kinds_scope):
    root = kinds_scope
    message = dispatch(KIND_REGISTRY, "repo", "update", "code", "codebase")
    assert message == "Renamed repository code -> codebase"
    assert (root / "repositories" / "codebase").exists()


def test_dispatch_update_subproject(kinds_scope):
    root = kinds_scope
    message = dispatch(KIND_REGISTRY, "sub", "update", "demo", "worker", "builder")
    assert message == "Renamed subproject demo/worker -> builder"
    assert (root / "projects" / "demo" / "builder.md").exists()


def test_dispatch_update_subproject_without_new_id_raises(kinds_scope):
    with pytest.raises(ValueError, match="Usage: owrap update subproject"):
        dispatch(KIND_REGISTRY, "subproject", "update", "demo", "worker")


def test_dispatch_unknown_kind_raises():
    with pytest.raises(ValueError, match="no such kind 'bogus'"):
        dispatch(KIND_REGISTRY, "bogus", "update", "a", "b")


def test_dispatch_unsupported_action_raises(kinds_scope):
    with pytest.raises(ValueError, match="project does not support add"):
        dispatch(KIND_REGISTRY, "project", "add", "demo")


def test_dispatch_add_decision(kinds_scope, capsys):
    root = kinds_scope
    dispatch(KIND_REGISTRY, "decision", "add", "abc123", "Use the new grammar")
    main_text = (root / "projects" / "demo" / "worker.md").read_text()
    assert "Use the new grammar" in main_text
    assert "DECISION added" in capsys.readouterr().out


def test_dispatch_add_and_clear_todo(kinds_scope, capsys):
    root = kinds_scope
    dispatch(KIND_REGISTRY, "todo", "add", "abc123", "Ship the kinds refactor")
    main_text = (root / "projects" / "demo" / "worker.md").read_text()
    assert "Ship the kinds refactor" in main_text
    captured = capsys.readouterr().out
    assert "GOAL added" in captured

    dispatch(KIND_REGISTRY, "todo", "update", "abc123", "1", "Ship it carefully")
    dispatch(KIND_REGISTRY, "todo", "clear", "abc123")
    captured = capsys.readouterr().out
    assert "GOALS cleared" in captured


def test_dispatch_remove_todo(kinds_scope, capsys):
    dispatch(KIND_REGISTRY, "todo", "add", "abc123", "Temporary goal")
    capsys.readouterr()
    dispatch(KIND_REGISTRY, "todo", "remove", "abc123", "1")
    assert "GOAL removed" in capsys.readouterr().out


def test_dispatch_add_remove_and_clear_decision(kinds_scope, capsys):
    dispatch(KIND_REGISTRY, "decision", "add", "abc123", "Pick option A")
    capsys.readouterr()
    dispatch(KIND_REGISTRY, "decision", "remove", "abc123", "1")
    assert "DECISION removed" in capsys.readouterr().out

    dispatch(KIND_REGISTRY, "decision", "add", "abc123", "Pick option B")
    capsys.readouterr()
    dispatch(KIND_REGISTRY, "decision", "clear", "abc123")
    assert "DECISIONS cleared" in capsys.readouterr().out


def test_dispatch_add_repository(kinds_scope):
    root = kinds_scope
    message = dispatch(KIND_REGISTRY, "repository", "add", "fresh", "/tmp/fresh")
    assert message == "Added repository fresh"
    assert (root / "repositories" / "fresh" / "fresh.yaml").exists()


def test_dispatch_remove_project_blocked_by_subproject(kinds_scope):
    with pytest.raises(ValueError, match="still has subproject"):
        dispatch(KIND_REGISTRY, "project", "remove", "demo")


def test_dispatch_remove_subproject_blocked_by_session(kinds_scope):
    with pytest.raises(ValueError, match="still targeted by session"):
        dispatch(KIND_REGISTRY, "subproject", "remove", "demo", "worker")


def test_dispatch_remove_repository_blocked_by_link(kinds_scope):
    with pytest.raises(ValueError, match="still linked to project"):
        dispatch(KIND_REGISTRY, "repository", "remove", "code")


def test_dispatch_remove_subproject_and_project_succeed(kinds_scope):
    root = kinds_scope
    message = dispatch(KIND_REGISTRY, "subproject", "remove", "spare", "loose")
    assert message == "Removed subproject spare/loose"
    assert not (root / "projects" / "spare" / "loose.md").exists()

    message = dispatch(KIND_REGISTRY, "project", "remove", "spare")
    assert message == "Removed project spare"
    assert not (root / "projects" / "spare").exists()


def test_dispatch_remove_repository_succeeds(kinds_scope):
    root = kinds_scope
    message = dispatch(KIND_REGISTRY, "repository", "remove", "extra")
    assert message == "Removed repository extra"
    assert not (root / "repositories" / "extra").exists()
