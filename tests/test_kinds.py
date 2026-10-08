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
