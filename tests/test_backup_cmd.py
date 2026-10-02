import pytest


def _patch_research_root(monkeypatch, tmp_path):
    research_root = tmp_path / "research_root"
    backups_dir = tmp_path / "owrap_home" / "backups"
    monkeypatch.setattr(
        "owrap.commands.backup_cmd.BACKUPS_DIR", backups_dir,
    )
    monkeypatch.setattr(
        "owrap.utils.paths._resolve_research_root", lambda: str(research_root),
    )
    return research_root, backups_dir


def _write(path, text="content"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_backup_errors_when_nothing_to_back_up(monkeypatch, tmp_path):
    from owrap.commands.backup_cmd import BackupRunner
    _patch_research_root(monkeypatch, tmp_path)

    with pytest.raises(SystemExit) as exc_info:
        BackupRunner().run("myresearch")
    assert exc_info.value.code == 1


def test_backup_copies_existing_files(monkeypatch, tmp_path):
    from owrap.commands.backup_cmd import BackupRunner
    research_root, backups_dir = _patch_research_root(monkeypatch, tmp_path)
    _write(research_root / "memory" / "myresearch.md", "memory content")
    _write(research_root / "projects" / "myresearch.md", "project content")

    BackupRunner().run("myresearch")

    snapshots = list((backups_dir / "myresearch").iterdir())
    assert len(snapshots) == 1
    snap = snapshots[0]
    assert (snap / "memory.md").read_text() == "memory content"
    assert (snap / "projects.md").read_text() == "project content"
    assert not (snap / "todo.md").exists()


def test_retrieve_lists_backups_when_no_timestamp_given(monkeypatch, tmp_path, capsys):
    from owrap.commands.backup_cmd import BackupRunner, RetrieveRunner
    research_root, backups_dir = _patch_research_root(monkeypatch, tmp_path)
    _write(research_root / "memory" / "myresearch.md", "v1")
    BackupRunner().run("myresearch")

    RetrieveRunner().run("myresearch")
    out = capsys.readouterr().out
    assert "Available backups" in out


def test_retrieve_errors_when_no_backups_exist(monkeypatch, tmp_path):
    from owrap.commands.backup_cmd import RetrieveRunner
    _patch_research_root(monkeypatch, tmp_path)

    with pytest.raises(SystemExit) as exc_info:
        RetrieveRunner().run("myresearch")
    assert exc_info.value.code == 1


def test_retrieve_restores_latest_over_live_file(monkeypatch, tmp_path):
    from owrap.commands.backup_cmd import BackupRunner, RetrieveRunner
    research_root, backups_dir = _patch_research_root(monkeypatch, tmp_path)
    memory_path = research_root / "memory" / "myresearch.md"
    _write(memory_path, "good content")
    BackupRunner().run("myresearch")

    # Simulate corruption after the backup.
    memory_path.write_text("corrupted!!")

    RetrieveRunner().run("myresearch", timestamp="latest")

    assert memory_path.read_text() == "good content"


def test_delete_errors_when_no_backups_exist(monkeypatch, tmp_path):
    from owrap.commands.backup_cmd import DeleteBackupRunner
    _patch_research_root(monkeypatch, tmp_path)

    with pytest.raises(SystemExit) as exc_info:
        DeleteBackupRunner().run("myresearch")
    assert exc_info.value.code == 1


def test_delete_latest_removes_only_newest_snapshot(monkeypatch, tmp_path):
    from owrap.commands.backup_cmd import BackupRunner, DeleteBackupRunner
    research_root, backups_dir = _patch_research_root(monkeypatch, tmp_path)
    _write(research_root / "memory" / "myresearch.md", "v1")
    timestamps = iter(["20260101T000000", "20260101T000001"])
    monkeypatch.setattr(
        "owrap.commands.backup_cmd.time.strftime", lambda _: next(timestamps),
    )
    BackupRunner().run("myresearch")
    BackupRunner().run("myresearch")

    DeleteBackupRunner().run("myresearch", which="latest")

    remaining = [p.name for p in (backups_dir / "myresearch").iterdir()]
    assert remaining == ["20260101T000000"]


def test_delete_all_removes_every_snapshot(monkeypatch, tmp_path):
    from owrap.commands.backup_cmd import BackupRunner, DeleteBackupRunner
    research_root, backups_dir = _patch_research_root(monkeypatch, tmp_path)
    _write(research_root / "memory" / "myresearch.md", "v1")
    BackupRunner().run("myresearch")
    BackupRunner().run("myresearch")

    DeleteBackupRunner().run("myresearch", which="all")

    assert not (backups_dir / "myresearch").exists()


def test_delete_specific_timestamp(monkeypatch, tmp_path):
    from owrap.commands.backup_cmd import BackupRunner, DeleteBackupRunner
    research_root, backups_dir = _patch_research_root(monkeypatch, tmp_path)
    _write(research_root / "memory" / "myresearch.md", "v1")
    BackupRunner().run("myresearch")
    ts = next((backups_dir / "myresearch").iterdir()).name

    DeleteBackupRunner().run("myresearch", which=ts)

    assert not (backups_dir / "myresearch" / ts).exists()


def test_delete_errors_on_unknown_timestamp(monkeypatch, tmp_path):
    from owrap.commands.backup_cmd import BackupRunner, DeleteBackupRunner
    research_root, backups_dir = _patch_research_root(monkeypatch, tmp_path)
    _write(research_root / "memory" / "myresearch.md", "v1")
    BackupRunner().run("myresearch")

    with pytest.raises(SystemExit) as exc_info:
        DeleteBackupRunner().run("myresearch", which="20000101T000000")
    assert exc_info.value.code == 2


def test_retrieve_resolves_unambiguous_prefix(monkeypatch, tmp_path):
    from owrap.commands.backup_cmd import BackupRunner, RetrieveRunner
    research_root, backups_dir = _patch_research_root(monkeypatch, tmp_path)
    memory_path = research_root / "memory" / "myresearch.md"
    _write(memory_path, "good content")
    monkeypatch.setattr(
        "owrap.commands.backup_cmd.time.strftime", lambda _: "20260101T000000",
    )
    BackupRunner().run("myresearch")
    memory_path.write_text("corrupted!!")

    RetrieveRunner().run("myresearch", timestamp="202601")

    assert memory_path.read_text() == "good content"


def test_delete_errors_on_ambiguous_prefix(monkeypatch, tmp_path, capsys):
    from owrap.commands.backup_cmd import BackupRunner, DeleteBackupRunner
    research_root, backups_dir = _patch_research_root(monkeypatch, tmp_path)
    _write(research_root / "memory" / "myresearch.md", "v1")
    timestamps = iter(["20260101T000000", "20260101T000001"])
    monkeypatch.setattr(
        "owrap.commands.backup_cmd.time.strftime", lambda _: next(timestamps),
    )
    BackupRunner().run("myresearch")
    BackupRunner().run("myresearch")

    with pytest.raises(SystemExit) as exc_info:
        DeleteBackupRunner().run("myresearch", which="20260101")
    assert exc_info.value.code == 2
    out = capsys.readouterr().out
    assert "AMBIGUOUS" in out
    # Neither snapshot was touched by the ambiguous, rejected call.
    assert len(list((backups_dir / "myresearch").iterdir())) == 2


def test_retrieve_errors_on_unknown_timestamp(monkeypatch, tmp_path):
    from owrap.commands.backup_cmd import BackupRunner, RetrieveRunner
    research_root, backups_dir = _patch_research_root(monkeypatch, tmp_path)
    _write(research_root / "memory" / "myresearch.md", "v1")
    BackupRunner().run("myresearch")

    with pytest.raises(SystemExit) as exc_info:
        RetrieveRunner().run("myresearch", timestamp="20000101T000000")
    assert exc_info.value.code == 2
