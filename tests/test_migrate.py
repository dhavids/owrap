import json
import subprocess
from pathlib import Path

import yaml

from owrap.commands.migrate import MigrateRunner
from owrap.utils.session.resolver import _parse


def _legacy(tmp_path: Path) -> tuple[Path, Path]:
    home = tmp_path / "home"
    root = tmp_path / "records"
    sessions = home / "sessions"
    artifacts = home / "docs" / "sessions" / "abc123"
    sessions.mkdir(parents=True)
    artifacts.mkdir(parents=True)
    (sessions / "abc123.session").write_text(
        "session_id=abc123\nresearch=owrap\narea=migration\nworkspace=test\n"
    )
    (artifacts / "context.md").write_text("session context")
    (root / "projects").mkdir(parents=True)
    (root / "memory").mkdir()
    (root / "todo").mkdir()
    (root / "projects" / "owrap.md").write_text(
        "# owrap\n\n## Overview\n\nOld overview.\n\n"
        "## migration\n\n### Status\n\nIn progress.\n"
    )
    (root / "memory" / "owrap.md").write_text(
        "## migration\n\n### Decisions\n\n- Preserve this.\n"
    )
    (root / "todo" / "owrap.md").write_text(
        "## migration\n\n- [ ] Finish migration\n"
    )
    config = home / "configs" / "test.json"
    config.parent.mkdir()
    config.write_text(json.dumps({"research_root": str(root)}))
    return home, root


def _repository(tmp_path: Path) -> Path:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    subprocess.run(
        ["git", "-C", str(checkout), "init", "-b", "dev"],
        check=True,
        capture_output=True,
    )
    return checkout


def test_preview_does_not_change_legacy_data(tmp_path):
    home, root = _legacy(tmp_path)

    plan = MigrateRunner().run(str(home), str(root))

    assert len(plan["sessions"]) == 1
    assert not (root / "projects" / "owrap" / "owrap.yaml").exists()
    assert (home / "docs" / "sessions" / "abc123").is_dir()


def test_apply_creates_records_and_moves_session_artifacts(tmp_path):
    home, root = _legacy(tmp_path)

    MigrateRunner().run(str(home), str(root), apply=True)

    record_dir = root / "projects" / "owrap"
    record = yaml.safe_load((record_dir / "owrap.yaml").read_text())
    session = _parse(home / "sessions" / "abc123.session")
    assert record["subprojects"]["migration"]["file"] == "migration.md"
    assert "Finish migration" in (record_dir / "migration.md").read_text()
    assert "Preserve this" in (record_dir / "migration.md").read_text()
    assert (record_dir / "legacy-project.md").is_file()
    assert session["target_kind"] == "project"
    assert session["project_id"] == "owrap"
    assert session["subproject_id"] == "migration"
    assert session["repositories"] == "[]"
    assert (
        home / "sessions" / "abc123" / "context.md"
    ).read_text() == "session context"
    assert not (home / "docs" / "sessions" / "abc123").exists()
    config = json.loads((home / "configs" / "test.json").read_text())
    assert config["docs_root"] == str(root)
    assert "research_root" not in config


def test_missing_parent_is_preserved_without_active_parent(tmp_path):
    home, root = _legacy(tmp_path)
    session = home / "sessions" / "abc123.session"
    session.write_text(session.read_text() + "parent_session_id=missing\n")

    MigrateRunner().run(str(home), str(root), apply=True)

    data = _parse(session)
    assert "parent_session_id" not in data
    assert data["legacy_parent_session_id"] == "missing"


def test_apply_is_idempotent(tmp_path):
    home, root = _legacy(tmp_path)
    runner = MigrateRunner()

    runner.run(str(home), str(root), apply=True)
    runner.run(str(home), str(root), apply=True)

    assert (root / "projects" / "owrap" / "main.md").is_file()


def test_legacy_ids_are_normalized_without_removing_old_fields(tmp_path):
    home, root = _legacy(tmp_path)
    session = home / "sessions" / "abc123.session"
    session.write_text(
        "session_id=abc123\nresearch=mpe_learner\n"
        "area=data_gen\nworkspace=test\n"
    )

    MigrateRunner().run(str(home), str(root), apply=True)

    data = _parse(session)
    assert data["research"] == "mpe_learner"
    assert data["area"] == "data_gen"
    assert data["project_id"] == "mpe-learner"
    assert data["subproject_id"] == "data-gen"
    assert (
        root / "projects" / "mpe-learner" / "mpe-learner.yaml"
    ).is_file()


def test_mapping_creates_repository_and_links_sessions(tmp_path):
    home, root = _legacy(tmp_path)
    checkout = _repository(tmp_path)
    mapping = tmp_path / "migration.yaml"
    mapping.write_text(
        yaml.safe_dump({
            "repositories": {
                "owrap-dev": {
                    "checkout": str(checkout),
                    "remote": "git@example.com:team/owrap.git",
                },
            },
            "projects": {"owrap": ["owrap-dev"]},
        }, sort_keys=False)
    )

    MigrateRunner().run(
        str(home), str(root), mapping=str(mapping), apply=True,
    )

    project = yaml.safe_load(
        (root / "projects" / "owrap" / "owrap.yaml").read_text()
    )
    repository = yaml.safe_load(
        (
            root / "repositories" / "owrap-dev" / "owrap-dev.yaml"
        ).read_text()
    )
    session = _parse(home / "sessions" / "abc123.session")
    assert project["repositories"] == ["owrap-dev"]
    assert repository["checkout"] == str(checkout)
    assert repository["remote"] == "git@example.com:team/owrap.git"
    assert session["repositories"] == '["owrap-dev"]'


def test_mapping_rejects_unknown_repository(tmp_path):
    home, root = _legacy(tmp_path)
    mapping = tmp_path / "migration.yaml"
    mapping.write_text("projects:\n  owrap: [missing]\n")

    try:
        MigrateRunner().run(str(home), str(root), mapping=str(mapping))
    except ValueError as error:
        assert "unknown repository" in str(error)
    else:
        raise AssertionError("invalid repository mapping was accepted")
