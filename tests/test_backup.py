import pytest


def _records(tmp_path, monkeypatch):
    """
    Create a project (with a linked repository and a plain subproject)
    plus a standalone repository, matching the canonical project/
    repository schema `owrap backup` now reads.
    """
    root = tmp_path / "research"
    project = root / "projects" / "proj"
    repo = root / "repositories" / "repo-a"
    other_repo = root / "repositories" / "repo-b"
    project.mkdir(parents=True)
    repo.mkdir(parents=True)
    other_repo.mkdir(parents=True)
    (project / "proj.yaml").write_text(
        "schema_version: 1\nkind: project\nid: proj\n"
        "main: main.md\nrepositories: [repo-a]\nsubprojects:\n"
        "  sub:\n    kind: regular\n    file: sub.md\n    parent: main\n"
    )
    (project / "main.md").write_text("# proj\n\nproject content\n")
    (project / "sub.md").write_text("# sub\n\nsubproject content\n")
    (repo / "repo-a.yaml").write_text(
        "schema_version: 1\nkind: repository\nid: repo-a\n"
        "main: memory.md\ncheckout: /tmp/repo-a\n"
    )
    (repo / "memory.md").write_text("repo-a content\n")
    (other_repo / "repo-b.yaml").write_text(
        "schema_version: 1\nkind: repository\nid: repo-b\n"
        "main: memory.md\ncheckout: /tmp/repo-b\n"
    )
    (other_repo / "memory.md").write_text("repo-b content\n")
    monkeypatch.setattr(
        "owrap.utils.memory.records.get_workspace_config",
        lambda workspace: {"research_root": str(root)},
    )
    return project, repo, other_repo


def _session(tmp_path, monkeypatch, sid="abc123", **fields):
    sessions = tmp_path / "sessions"
    sessions.mkdir(exist_ok=True)
    body = "".join(f"{k}={v}\n" for k, v in fields.items())
    sfile = sessions / f"{sid}.session"
    sfile.write_text(f"session_id={sid}\n{body}")
    monkeypatch.setattr(
        "owrap.commands.backup.resolve_session_or_exit", lambda token: sid,
    )
    monkeypatch.setattr("owrap.commands.backup.session_file", lambda s: sfile)
    monkeypatch.delenv("SESSION_ID", raising=False)
    return sfile


def _patch_backups_dir(monkeypatch, tmp_path):
    backups_dir = tmp_path / "owrap_home" / "backups"
    monkeypatch.setattr("owrap.commands.backup.BACKUPS_DIR", backups_dir)
    return backups_dir


@pytest.fixture
def project_backup(tmp_path, monkeypatch):
    from owrap.commands.backup import BackupRunner, RetrieveRunner, DeleteBackupRunner
    project, repo, _ = _records(tmp_path, monkeypatch)
    backups_dir = _patch_backups_dir(monkeypatch, tmp_path)
    _session(
        tmp_path, monkeypatch,
        target_kind="project", project_id="proj", workspace="test",
    )
    return {
        "project": project, "repo": repo, "backups_dir": backups_dir,
        "Backup": BackupRunner, "Retrieve": RetrieveRunner,
        "Delete": DeleteBackupRunner,
    }


class TestBackupRunner:
    def test_copies_project_and_repository_files(self, project_backup):
        project_backup["Backup"]().run("abc123")

        snapshots = list(
            (project_backup["backups_dir"] / "project" / "proj").iterdir()
        )
        assert len(snapshots) == 1
        snap = snapshots[0]
        assert (snap / "main.md").read_text() == "# proj\n\nproject content\n"
        assert (snap / "repo-a--memory.md").read_text() == "repo-a content\n"

    def test_errors_when_nothing_to_back_up(self, tmp_path, monkeypatch):
        from owrap.commands.backup import BackupRunner
        _, _, other_repo = _records(tmp_path, monkeypatch)
        (other_repo / "memory.md").unlink()
        _patch_backups_dir(monkeypatch, tmp_path)
        _session(
            tmp_path, monkeypatch,
            target_kind="repository", repository_id="repo-b", workspace="test",
        )

        with pytest.raises(SystemExit) as exc_info:
            BackupRunner().run("abc123")
        assert exc_info.value.code == 1

    def test_subproject_backs_up_its_own_file_and_inherited_repository(
        self, tmp_path, monkeypatch,
    ):
        from owrap.commands.backup import BackupRunner
        _records(tmp_path, monkeypatch)
        backups_dir = _patch_backups_dir(monkeypatch, tmp_path)
        _session(
            tmp_path, monkeypatch,
            target_kind="project", project_id="proj", subproject_id="sub",
            workspace="test",
        )

        BackupRunner().run("abc123")

        snap = next((backups_dir / "project" / "proj" / "sub").iterdir())
        assert (snap / "sub.md").read_text() == "# sub\n\nsubproject content\n"
        assert (snap / "repo-a--memory.md").exists()

    def test_repository_only_session_backs_up_its_memory_file(
        self, tmp_path, monkeypatch,
    ):
        from owrap.commands.backup import BackupRunner
        _records(tmp_path, monkeypatch)
        backups_dir = _patch_backups_dir(monkeypatch, tmp_path)
        _session(
            tmp_path, monkeypatch,
            target_kind="repository", repository_id="repo-b", workspace="test",
        )

        BackupRunner().run("abc123")

        snap = next((backups_dir / "repository" / "repo-b").iterdir())
        assert (snap / "repo-b--memory.md").read_text() == "repo-b content\n"


class TestRetrieveRunner:
    def test_lists_backups_when_no_timestamp_given(self, project_backup, capsys):
        project_backup["Backup"]().run("abc123")

        project_backup["Retrieve"]().run("abc123")

        out = capsys.readouterr().out
        assert "Available backups" in out

    def test_errors_when_no_backups_exist(self, project_backup):
        with pytest.raises(SystemExit) as exc_info:
            project_backup["Retrieve"]().run("abc123")
        assert exc_info.value.code == 1

    def test_restores_latest_over_live_files(self, project_backup):
        project_backup["Backup"]().run("abc123")
        (project_backup["project"] / "main.md").write_text("corrupted!!")
        (project_backup["repo"] / "memory.md").write_text("corrupted!!")

        project_backup["Retrieve"]().run("abc123", timestamp="latest")

        assert (
            project_backup["project"] / "main.md"
        ).read_text() == "# proj\n\nproject content\n"
        assert (
            project_backup["repo"] / "memory.md"
        ).read_text() == "repo-a content\n"

    def test_resolves_unambiguous_prefix(self, project_backup, monkeypatch):
        monkeypatch.setattr(
            "owrap.commands.backup.time.strftime", lambda _: "20260101T000000",
        )
        project_backup["Backup"]().run("abc123")
        (project_backup["project"] / "main.md").write_text("corrupted!!")

        project_backup["Retrieve"]().run("abc123", timestamp="202601")

        assert (
            project_backup["project"] / "main.md"
        ).read_text() == "# proj\n\nproject content\n"

    def test_errors_on_unknown_timestamp(self, project_backup):
        project_backup["Backup"]().run("abc123")

        with pytest.raises(SystemExit) as exc_info:
            project_backup["Retrieve"]().run("abc123", timestamp="20000101T000000")
        assert exc_info.value.code == 2


class TestDeleteBackupRunner:
    def test_errors_when_no_backups_exist(self, project_backup):
        with pytest.raises(SystemExit) as exc_info:
            project_backup["Delete"]().run("abc123")
        assert exc_info.value.code == 1

    def test_latest_removes_only_newest_snapshot(self, project_backup, monkeypatch):
        timestamps = iter(["20260101T000000", "20260101T000001"])
        monkeypatch.setattr(
            "owrap.commands.backup.time.strftime", lambda _: next(timestamps),
        )
        project_backup["Backup"]().run("abc123")
        project_backup["Backup"]().run("abc123")

        project_backup["Delete"]().run("abc123", which="latest")

        remaining = [
            p.name for p in
            (project_backup["backups_dir"] / "project" / "proj").iterdir()
        ]
        assert remaining == ["20260101T000000"]

    def test_all_removes_every_snapshot(self, project_backup):
        project_backup["Backup"]().run("abc123")
        project_backup["Backup"]().run("abc123")

        project_backup["Delete"]().run("abc123", which="all")

        assert not (project_backup["backups_dir"] / "project" / "proj").exists()

    def test_specific_timestamp(self, project_backup):
        project_backup["Backup"]().run("abc123")
        snap_dir = project_backup["backups_dir"] / "project" / "proj"
        ts = next(snap_dir.iterdir()).name

        project_backup["Delete"]().run("abc123", which=ts)

        assert not (snap_dir / ts).exists()

    def test_errors_on_unknown_timestamp(self, project_backup):
        project_backup["Backup"]().run("abc123")

        with pytest.raises(SystemExit) as exc_info:
            project_backup["Delete"]().run("abc123", which="20000101T000000")
        assert exc_info.value.code == 2

    def test_errors_on_ambiguous_prefix(self, project_backup, monkeypatch, capsys):
        timestamps = iter(["20260101T000000", "20260101T000001"])
        monkeypatch.setattr(
            "owrap.commands.backup.time.strftime", lambda _: next(timestamps),
        )
        project_backup["Backup"]().run("abc123")
        project_backup["Backup"]().run("abc123")

        with pytest.raises(SystemExit) as exc_info:
            project_backup["Delete"]().run("abc123", which="20260101")
        assert exc_info.value.code == 2
        out = capsys.readouterr().out
        assert "AMBIGUOUS" in out
        snap_dir = project_backup["backups_dir"] / "project" / "proj"
        assert len(list(snap_dir.iterdir())) == 2
