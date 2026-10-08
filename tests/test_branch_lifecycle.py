import pytest

from owrap.commands.branch import BranchRunner
from owrap.utils.memory.records import resolve_memory_target


def _project(tmp_path, monkeypatch):
    root = tmp_path / "research"
    project = root / "projects" / "example"
    repository = root / "repositories" / "code"
    project.mkdir(parents=True)
    repository.mkdir(parents=True)
    (project / "example.yaml").write_text(
        "schema_version: 1\nkind: project\nid: example\n"
        "title: Example\nmain: main.md\n"
        "repositories: [code]\nsubprojects: {}\n"
    )
    (project / "main.md").write_text(
        "# Example\n\n## Goals\n\n- [ ] Shared goal\n\n"
        "## Status\n\nCurrent parent status.\n\n"
        "## Decisions\n\n## Notes\n\nPrivate note.\n"
    )
    (repository / "code.yaml").write_text(
        "schema_version: 1\nkind: repository\nid: code\n"
        f"main: memory.md\ncheckout: {tmp_path / 'checkout'}\n"
    )
    (repository / "memory.md").write_text("# Code\n")
    (tmp_path / "checkout").mkdir()
    monkeypatch.setattr(
        "owrap.utils.memory.records.get_workspace_config",
        lambda workspace: {"docs_root": str(root)},
    )
    return project


def test_branch_create_preview_merge_and_archive(tmp_path, monkeypatch):
    project = _project(tmp_path, monkeypatch)
    runner = BranchRunner()

    branch_path = runner.create(
        "example", "trial", "main", "code", "trial/example", "test",
    )
    assert branch_path == project / "trial.md"
    assert "parent: main" in (project / "example.yaml").read_text()
    branch_path.write_text(
        branch_path.read_text().replace(
            "## Goals\n", "## Goals\n\n- [ ] New goal\n"
            "- [ ] Shared goal\n- [x] Completed goal\n",
        ).replace(
            "## Decisions\n", "## Decisions\n\n"
            "- 2026-10-04 — Keep parser small — simple interface\n",
        ).replace(
            "## Findings\n", "## Findings\n\n"
            "- parser.py handles CLI flags.\n",
        )
    )
    parent_path = project / "main.md"
    original = parent_path.read_text()

    preview = runner.merge("example", "trial", workspace="test")

    assert not preview["applied"]
    assert preview["goals"] == ["New goal"]
    assert "parser.py" in preview["findings"]
    assert len(preview["decisions"]) == 1
    assert parent_path.read_text() == original
    assert branch_path.exists()

    applied = runner.merge("example", "trial", apply=True, workspace="test")

    assert applied["applied"]
    text = parent_path.read_text()
    assert text.count("New goal") == 1
    assert text.count("Shared goal") == 1
    assert "Completed goal" not in text
    assert "parser.py handles CLI flags" in text
    assert "Keep parser small" in text
    assert "Private note." in text
    assert "Current parent status." in text
    archive = project / "trial.archived.md"
    assert archive.exists()
    assert not branch_path.exists()
    assert "Documentation only; Git was not changed" in archive.read_text()
    record = (project / "example.yaml").read_text()
    assert "archived: true" in record
    assert "merged_into: main" in record

    with pytest.raises(ValueError, match="archived subproject"):
        resolve_memory_target({
            "target_kind": "project", "project_id": "example",
            "subproject_id": "trial", "workspace": "test",
        })
    with pytest.raises(ValueError, match="already archived"):
        runner.merge("example", "trial", apply=True, workspace="test")


def test_branch_create_rejects_unlinked_repository(tmp_path, monkeypatch):
    project = _project(tmp_path, monkeypatch)

    with pytest.raises(ValueError, match="not linked"):
        BranchRunner().create(
            "example", "trial", "main", "other", "trial/example", "test",
        )

    assert not (project / "trial.md").exists()
    assert "trial" not in (project / "example.yaml").read_text()


def test_branch_merge_uses_declared_subproject_parent(tmp_path, monkeypatch):
    project = _project(tmp_path, monkeypatch)
    yaml_path = project / "example.yaml"
    yaml_path.write_text(
        yaml_path.read_text().replace(
            "subprojects: {}",
            "subprojects:\n  feature:\n    kind: regular\n"
            "    file: feature.md\n    parent: main",
        )
    )
    feature = project / "feature.md"
    feature.write_text(
        "# Feature\n\n## Goals\n\n## Status\n\n## Decisions\n\n"
        "## Findings\n\n## Notes\n",
    )
    branch = BranchRunner().create(
        "example", "trial", "feature", "code", "trial/feature", "test",
    )
    branch.write_text(
        branch.read_text().replace("## Goals\n", "## Goals\n\n- [ ] Child goal\n")
    )

    BranchRunner().merge("example", "trial", apply=True, workspace="test")

    assert "Child goal" in feature.read_text()
    assert "Child goal" not in (project / "main.md").read_text()
    assert "merged_into: feature" in yaml_path.read_text()
