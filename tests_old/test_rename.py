import pytest

from owrap.commands.rename import RenameRunner
from owrap.utils.session import resolver


@pytest.fixture
def rename_scope(tmp_path, monkeypatch):
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
        "    parent: main\n    repositories: [code]\n"
        "  child:\n    kind: regular\n    file: child.md\n"
        "    parent: worker\n"
    )
    (project / "main.md").write_text("# Demo\n\n## Goals\n")
    (project / "worker.md").write_text(
        "# Worker\n\n## Overview\n\nPart of [demo](main.md).\n\n## Goals\n"
    )
    (project / "child.md").write_text("# Child\n\n## Goals\n")
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
    return root, session_path


def test_rename_project_moves_directory_and_updates_sessions(rename_scope):
    root, session_path = rename_scope

    RenameRunner().project("demo", "renamed")

    assert not (root / "projects" / "demo").exists()
    new_dir = root / "projects" / "renamed"
    assert (new_dir / "renamed.yaml").exists()
    assert "id: renamed" in (new_dir / "renamed.yaml").read_text()
    assert resolver._parse(session_path)["project_id"] == "renamed"


def test_rename_project_rewrites_subproject_backrefs(rename_scope):
    root, _ = rename_scope

    RenameRunner().project("demo", "renamed")

    worker_text = (root / "projects" / "renamed" / "worker.md").read_text()
    assert "[renamed](main.md)" in worker_text
    assert "[demo](main.md)" not in worker_text


def test_rename_project_rejects_existing_new_id(rename_scope):
    root, _ = rename_scope
    (root / "projects" / "other").mkdir(parents=True)

    with pytest.raises(FileExistsError):
        RenameRunner().project("demo", "other")


def test_rename_subproject_updates_key_and_sessions(rename_scope):
    root, session_path = rename_scope

    RenameRunner().subproject("demo", "worker", "renamed-sub")

    record_text = (root / "projects" / "demo" / "demo.yaml").read_text()
    assert "renamed-sub" in record_text
    assert "worker:" not in record_text
    assert resolver._parse(session_path)["subproject_id"] == "renamed-sub"


def test_rename_subproject_also_renames_underlying_file(rename_scope):
    root, _ = rename_scope
    project_dir = root / "projects" / "demo"

    RenameRunner().subproject("demo", "worker", "renamed-sub")

    assert not (project_dir / "worker.md").exists()
    assert (project_dir / "renamed-sub.md").exists()
    import yaml
    record = yaml.safe_load((project_dir / "demo.yaml").read_text())
    assert record["subprojects"]["renamed-sub"]["file"] == "renamed-sub.md"


def test_rename_project_moves_backup_dir(rename_scope, tmp_path, monkeypatch):
    backups_dir = tmp_path / "backups"
    monkeypatch.setattr("owrap.commands.rename.BACKUPS_DIR", backups_dir)
    old_backup = backups_dir / "project" / "demo" / "20260101T000000Z"
    old_backup.mkdir(parents=True)
    (old_backup / "main.md").write_text("snapshot")

    RenameRunner().project("demo", "renamed")

    assert not (backups_dir / "project" / "demo").exists()
    assert (
        backups_dir / "project" / "renamed" / "20260101T000000Z" / "main.md"
    ).read_text() == "snapshot"


def test_rename_subproject_moves_backup_dir(rename_scope, tmp_path, monkeypatch):
    backups_dir = tmp_path / "backups"
    monkeypatch.setattr("owrap.commands.rename.BACKUPS_DIR", backups_dir)
    old_backup = backups_dir / "project" / "demo" / "worker" / "20260101T000000Z"
    old_backup.mkdir(parents=True)
    (old_backup / "worker.md").write_text("snapshot")

    RenameRunner().subproject("demo", "worker", "renamed-sub")

    assert not (backups_dir / "project" / "demo" / "worker").exists()
    assert (
        backups_dir / "project" / "demo" / "renamed-sub"
        / "20260101T000000Z" / "worker.md"
    ).read_text() == "snapshot"


def test_rename_repository_moves_backup_dir(rename_scope, tmp_path, monkeypatch):
    backups_dir = tmp_path / "backups"
    monkeypatch.setattr("owrap.commands.rename.BACKUPS_DIR", backups_dir)
    old_backup = backups_dir / "repository" / "code" / "20260101T000000Z"
    old_backup.mkdir(parents=True)
    (old_backup / "memory.md").write_text("snapshot")

    RenameRunner().repository("code", "renamed-repo")

    assert not (backups_dir / "repository" / "code").exists()
    assert (
        backups_dir / "repository" / "renamed-repo"
        / "20260101T000000Z" / "memory.md"
    ).read_text() == "snapshot"


def test_rename_subproject_updates_parent_references(rename_scope):
    root, _ = rename_scope

    RenameRunner().subproject("demo", "worker", "renamed-sub")

    import yaml
    record = yaml.safe_load(
        (root / "projects" / "demo" / "demo.yaml").read_text()
    )
    assert record["subprojects"]["child"]["parent"] == "renamed-sub"


def test_rename_subproject_rejects_unknown_old_id(rename_scope):
    with pytest.raises(ValueError):
        RenameRunner().subproject("demo", "nope", "new-name")


def test_rename_repository_relinks_projects_and_sessions(rename_scope):
    root, session_path = rename_scope

    RenameRunner().repository("code", "renamed-repo")

    assert not (root / "repositories" / "code").exists()
    assert (root / "repositories" / "renamed-repo" / "renamed-repo.yaml").exists()

    import yaml
    record = yaml.safe_load(
        (root / "projects" / "demo" / "demo.yaml").read_text()
    )
    assert record["repositories"] == ["renamed-repo"]
    assert record["subprojects"]["worker"]["repositories"] == ["renamed-repo"]
    assert resolver._parse(session_path)["repositories"] == '["renamed-repo"]'


def test_rename_repository_rejects_existing_new_id(rename_scope):
    root, _ = rename_scope
    (root / "repositories" / "taken").mkdir(parents=True)

    with pytest.raises(FileExistsError):
        RenameRunner().repository("code", "taken")


def test_rename_project_resolves_via_session_id(rename_scope, tmp_path):
    root, _ = rename_scope

    RenameRunner().project("abc123", "renamed")

    assert not (root / "projects" / "demo").exists()
    assert (root / "projects" / "renamed").is_dir()


def test_rename_project_refuses_an_ambiguous_token(rename_scope, tmp_path):
    root, session_path = rename_scope
    other_project = root / "projects" / "other"
    other_project.mkdir(parents=True)
    (other_project / "other.yaml").write_text(
        "schema_version: 1\nkind: project\nid: other\nmain: main.md\n"
        "repositories: []\nsubprojects: {}\n"
    )
    (other_project / "main.md").write_text("# Other\n\n## Goals\n")
    # Token "abc123" hits session_path by session_id (project_id=demo)
    # and second_session by project_id (literally "abc123") — two
    # different resolved values, hence ambiguous.
    second_session = session_path.parent.parent / "def456" / ".session"
    second_session.parent.mkdir()
    second_session.write_text(
        "session_id=def456\ntarget_kind=project\nproject_id=abc123\n"
        "workspace=test\n"
    )

    with pytest.raises(ValueError, match="matches more than one"):
        RenameRunner().project("abc123", "renamed")

    assert (root / "projects" / "demo").exists()
    assert (root / "projects" / "other").exists()
