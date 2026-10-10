"""
`Branch`'s documentation-merge transaction (kind/record/branch.py):
`_merge_document`'s text-combining rules, and `_merge_branch`'s
file-level all-or-nothing apply -- a real multi-file write with
rollback-on-exception, exactly the kind of thing that looks right on
a read-through but needs to actually be exercised to be sure the
rollback really restores every file it touched.
"""
from datetime import date
from types import SimpleNamespace

import pytest
import yaml

from owrap.kind.record import branch as branch_mod
from owrap.kind.record.branch import _merge_branch, _merge_document


# _merge_document (pure text merge, no filesystem)

def test_merge_document_copies_only_pending_non_duplicate_goals():
    goals = {
        "parent": [(True, "Done thing"), (False, "Already pending")],
        "branch": [
            (False, "Already pending"),  # duplicate (case-insensitive) -- skipped
            (False, "New goal"),
            (True, "Finished in branch"),  # done -- skipped
        ],
    }
    merged, pending, findings, decisions = _merge_document(
        "## Goals\n\n- [ ] Already pending\n", "## Goals\n", "feature-x", goals,
    )
    assert pending == ["New goal"]
    assert "- [ ] New goal" in merged
    assert merged.count("Already pending") == 1  # not duplicated


def test_merge_document_nests_findings_under_branch_heading():
    branch = "## Findings\n\n### A finding\n\nsome detail\n"
    merged, _, findings, _ = _merge_document(
        "## Findings\n", branch, "feature-x", {"parent": [], "branch": []},
    )
    assert "### From feature-x" in merged
    # the branch's own "### " subheading nests one level deeper once it's
    # folded under the new "### From feature-x" wrapper heading
    assert "#### A finding" in merged
    assert "### A finding" not in findings.replace("#### A finding", "")


def test_merge_document_skips_decisions_already_in_parent():
    parent = "## Decisions\n\n- Use X — because Y\n"
    branch = "## Decisions\n\n- Use X — because Y\n- Use Z — because W\n"
    merged, _, _, decisions = _merge_document(
        parent, branch, "feature-x", {"parent": [], "branch": []},
    )
    assert decisions == ["- Use Z — because W"]
    assert merged.count("Use X") == 1


# _merge_branch (real files, transactional apply)

def _setup_project(tmp_path, parent_text, branch_text):
    directory = tmp_path / "projects" / "myproj"
    directory.mkdir(parents=True)
    yaml_path = directory / "myproj.yaml"
    parent_path = directory / "main.md"
    branch_path = directory / "feature-x.md"
    parent_path.write_text(parent_text)
    branch_path.write_text(branch_text)
    record = {
        "kind": "project", "id": "myproj", "schema_version": 1,
        "main": "main.md", "repositories": [],
        "subprojects": {
            "feature-x": {
                "kind": "branch", "file": "feature-x.md", "parent": "main",
                "branch_repository": "myrepo", "branch_ref": "feature/x",
            },
        },
    }
    yaml_path.write_text(yaml.safe_dump(record))
    return yaml_path, parent_path, branch_path


@pytest.fixture
def project(tmp_path, monkeypatch):
    parent_text = "## Overview\n\nMain.\n\n## Goals\n\n## Decisions\n\n## Findings\n"
    branch_text = (
        "## Goals\n\n- [ ] New work\n\n"
        "## Decisions\n\n- Picked approach A — faster\n\n"
        "## Findings\n\n### Detail\n\nit works\n"
    )
    yaml_path, parent_path, branch_path = _setup_project(
        tmp_path, parent_text, branch_text,
    )
    monkeypatch.setattr(branch_mod, "resolve_root", lambda workspace="": tmp_path)
    monkeypatch.setattr(
        branch_mod, "resolve_memory_target",
        lambda session: SimpleNamespace(project_path=parent_path),
    )
    return SimpleNamespace(
        yaml_path=yaml_path, parent_path=parent_path, branch_path=branch_path,
        parent_text=parent_text, branch_text=branch_text,
    )


def test_preview_does_not_touch_any_file(project):
    result = _merge_branch("myproj", "feature-x", apply=False)
    assert result["applied"] is False
    assert project.parent_path.read_text() == project.parent_text
    assert project.branch_path.exists()
    assert not (project.yaml_path.parent / "feature-x.archived.md").exists()


def test_apply_merges_parent_archives_branch_updates_yaml(project):
    result = _merge_branch("myproj", "feature-x", apply=True)
    assert result["applied"] is True

    merged_parent = project.parent_path.read_text()
    assert "New work" in merged_parent
    assert "Picked approach A" in merged_parent
    assert "From feature-x" in merged_parent

    assert not project.branch_path.exists()
    archive_path = project.yaml_path.parent / "feature-x.archived.md"
    assert archive_path.exists()
    assert "Merged into [main]" in archive_path.read_text()

    record = yaml.safe_load(project.yaml_path.read_text())
    entry = record["subprojects"]["feature-x"]
    assert entry["archived"] is True
    assert entry["file"] == "feature-x.archived.md"
    assert entry["merged_into"] == "main"
    assert entry["merged_at"] == date.today().isoformat()


def test_apply_rolls_back_every_file_when_the_second_write_fails(project, monkeypatch):
    """
    The transaction writes the archive file, then the parent, then
    the yaml record, then deletes the branch file. Force a failure
    on the SECOND write (the yaml record) -- after the archive and
    parent files have already been touched -- and confirm every one
    of them is restored to its pre-merge state, not left half-merged.
    """
    original_write_atomic = branch_mod._write_atomic
    calls = []

    def _flaky_write_atomic(path, content):
        calls.append(path)
        if len(calls) == 2:
            raise OSError("disk full (simulated)")
        return original_write_atomic(path, content)

    monkeypatch.setattr(branch_mod, "_write_atomic", _flaky_write_atomic)

    with pytest.raises(OSError, match="disk full"):
        _merge_branch("myproj", "feature-x", apply=True)

    assert project.parent_path.read_text() == project.parent_text
    assert project.yaml_path.read_text() == yaml.safe_dump(yaml.safe_load(
        project.yaml_path.read_text(),
    ))  # still valid/unchanged yaml
    record = yaml.safe_load(project.yaml_path.read_text())
    assert "archived" not in record["subprojects"]["feature-x"]
    assert not (project.yaml_path.parent / "feature-x.archived.md").exists()
    assert project.branch_path.exists()  # never unlinked


def test_rejects_already_archived_branch(project):
    record = yaml.safe_load(project.yaml_path.read_text())
    record["subprojects"]["feature-x"]["archived"] = True
    project.yaml_path.write_text(yaml.safe_dump(record))

    with pytest.raises(ValueError, match="already archived"):
        _merge_branch("myproj", "feature-x", apply=True)
