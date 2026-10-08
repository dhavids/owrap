import json
import time
from unittest.mock import MagicMock

import pytest

from owrap.commands.get import GetRunner
from owrap.commands.context_manager import CtxWorkerRunner
from owrap.commands.todo import TodoRunner
from owrap.utils.memory.records import (
    count_bullets, normalize_identity_kind, resolve_memory_target,
    touched_repository_paths,
)
from owrap.utils.session import resolver


def _records(tmp_path, monkeypatch):
    root = tmp_path / "research"
    project = root / "projects" / "owrap"
    repo = root / "repositories" / "owrap-dev"
    project.mkdir(parents=True)
    repo.mkdir(parents=True)
    (project / "owrap.yaml").write_text(
        "schema_version: 1\nkind: project\nid: owrap\n"
        "main: main.md\nrepositories: [owrap-dev]\nsubprojects:\n"
        "  migration:\n    kind: regular\n    file: migration.md\n"
        "    parent: main\n"
        "  migration-trial:\n    kind: branch\n"
        "    file: migration-trial.md\n    parent: migration\n"
        "    branch_repository: owrap-dev\n"
        "    branch_ref: trial/migration\n"
    )
    (project / "main.md").write_text(
        "# owrap\n\n## Goals\n\n- [ ] Project goal\n\n## Notes\n\nKeep this.\n"
    )
    (project / "migration.md").write_text(
        "# Migration\n\n## Goals\n\n- [ ] Existing goal\n\n"
        "## Notes\n\nDo not change this.\n"
    )
    (project / "migration-trial.md").write_text(
        "# Trial\n\n## Goals\n\n- [ ] Trial goal\n"
    )
    (repo / "owrap-dev.yaml").write_text(
        "schema_version: 1\nkind: repository\nid: owrap-dev\n"
        "main: memory.md\ncheckout: /tmp/owrap-dev\n"
    )
    (repo / "memory.md").write_text("# Architecture\n\nRepository facts.\n")
    monkeypatch.setattr(
        "owrap.utils.memory.records.get_workspace_config",
        lambda workspace: {"docs_root": str(root)},
    )
    return root, project, repo


def test_subproject_resolves_inherited_repository(tmp_path, monkeypatch):
    _, project, repo = _records(tmp_path, monkeypatch)
    session = {
        "target_kind": "project", "project_id": "owrap",
        "subproject_id": "migration", "workspace": "test",
    }

    target = resolve_memory_target(session)

    assert target.project_path == project / "migration.md"
    assert target.repository_ids == ("owrap-dev",)
    assert target.repository_paths == (repo / "memory.md",)

    session["subproject_id"] = "migration-trial"
    branch = resolve_memory_target(session)
    assert branch.branch_parent == "migration"
    assert branch.branch_repository == "owrap-dev"
    assert branch.branch_ref == "trial/migration"


def test_todo_edits_subproject_goals_and_get_reads_records(
    tmp_path, monkeypatch, capsys,
):
    _, project, _ = _records(tmp_path, monkeypatch)
    home = tmp_path / "state"
    sessions = home / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    session_file = sessions / "abc123.session"
    session_file.write_text(
        "session_id=abc123\ntarget_kind=project\nproject_id=owrap\n"
        "subproject_id=migration\nworkspace=test\n"
        f"repositories={json.dumps(['owrap-dev'])}\n"
    )
    monkeypatch.setattr(
        "owrap.commands.todo.resolve_session_or_exit",
        lambda token: "abc123",
    )
    monkeypatch.setattr(
        "owrap.commands.todo.session_file",
        lambda sid: session_file,
    )
    monkeypatch.setattr(
        "owrap.commands.get.session_file",
        lambda sid: session_file,
    )
    monkeypatch.setattr("owrap.commands.get.RUNTIME_HOME", home)

    TodoRunner().run("owrap/migration", "New migration goal")
    TodoRunner().run_done("owrap/migration", "New migration goal")
    GetRunner().run("todo", session_id="abc123")
    output = capsys.readouterr().out

    assert "2. [x] New migration goal" in output
    assert "Do not change this." in (project / "migration.md").read_text()
    assert "Project goal" in (project / "main.md").read_text()

    GetRunner().run("memory", session_id="abc123")
    assert "Repository facts." in capsys.readouterr().out

    GetRunner().run("sub", session_id="abc123")
    assert capsys.readouterr().out.strip() == "migration"
    GetRunner().run("repo", session_id="abc123")
    assert capsys.readouterr().out.strip() == "owrap-dev"
    GetRunner().run("proj", session_id="abc123")
    assert "Existing goal" in capsys.readouterr().out


def test_attach_resolves_explicit_identity(monkeypatch):
    sessions = [
        {"session_id": "proj", "project_id": "owrap",
         "subproject_id": "migration"},
        {"session_id": "repo", "repository_id": "owrap-dev"},
    ]
    monkeypatch.setattr(resolver, "list_sessions", lambda: sessions)
    monkeypatch.setattr(
        resolver, "session_file", lambda token: MagicMock(
            exists=lambda: False,
        ),
    )

    assert resolver.resolve_attach_target("owrap/migration")[1][
        "session_id"
    ] == "proj"
    assert resolver.resolve_attach_target("owrap-dev")[1][
        "session_id"
    ] == "repo"


def test_sub_selects_existing_subproject_record(tmp_path, monkeypatch):
    """
    'owrap sub <id>' selecting an existing subproject sets its repositories
    and, for a branch-kind subproject, its branch fields.
    """
    from owrap.commands.project import ProjectRunner

    _records(tmp_path, monkeypatch)
    session_file = tmp_path / "abc123.session"
    session_file.write_text(
        "session_id=abc123\ntarget_kind=project\nproject_id=owrap\n"
        "subproject_id=\nworkspace=test\n"
    )
    monkeypatch.setattr(
        "owrap.commands.project.resolve", lambda mode: ("abc123", session_file, ""),
    )
    monkeypatch.setattr(resolver, "session_file", lambda sid: session_file)

    ProjectRunner().sub("migration")

    data = resolver._parse(session_file)
    assert data["subproject_id"] == "migration"
    assert json.loads(data["repositories"]) == ["owrap-dev"]

    ProjectRunner().sub("migration-trial")
    branch_data = resolver._parse(session_file)
    assert branch_data["branch_parent"] == "migration"
    assert branch_data["branch_repository"] == "owrap-dev"


def test_touched_repository_record_and_explicit_merge(tmp_path, monkeypatch):
    _, project, repo = _records(tmp_path, monkeypatch)
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    source = checkout / "module.py"
    source.write_text("pass\n")
    yaml_path = repo / "owrap-dev.yaml"
    yaml_path.write_text(
        yaml_path.read_text().replace("/tmp/owrap-dev", str(checkout))
    )
    session = {
        "target_kind": "project", "project_id": "owrap",
        "subproject_id": "migration", "workspace": "test",
    }
    target = resolve_memory_target(session)
    touched = touched_repository_paths(target, [str(source)], "test")
    assert touched == {"owrap-dev": repo / "memory.md"}
    assert touched_repository_paths(target, ["/tmp/other.py"], "test") == {}

    project_path = project / "migration.md"
    original_snapshot = project_path.read_bytes()
    output = (
        "# Subproject: migration\n## Status\nMigration running.\n"
        "## Decisions\n- Keep dev isolated — protects live\n"
        "# Repository: owrap-dev\n## Components\n"
        "- module.py — parser\n"
    )
    runner = CtxWorkerRunner()
    context_path = tmp_path / "context.md"
    runner._apply_record_output(
        output, context_path, project_path, touched, "sid", original_snapshot,
        project_section="Subproject: migration",
    )
    runner._apply_record_output(
        output, context_path, project_path, touched, "sid",
        project_path.read_bytes(),
        project_section="Subproject: migration",
    )
    project_text = project_path.read_text()
    repo_text = (repo / "memory.md").read_text()
    assert "Migration running." in project_text
    assert "Do not change this." in project_text
    assert project_text.count("Keep dev isolated") == 1
    assert repo_text.count("module.py — parser") == 1
    assert "Repository facts." in repo_text


def test_touched_paths_select_only_the_matching_repository(tmp_path, monkeypatch):
    _, project, repo = _records(tmp_path, monkeypatch)
    other = repo.parent / "other"
    other.mkdir()
    first_checkout = tmp_path / "first"
    second_checkout = tmp_path / "second"
    first_checkout.mkdir()
    second_checkout.mkdir()
    source = second_checkout / "changed.py"
    source.write_text("pass\n")
    yaml_path = repo / "owrap-dev.yaml"
    yaml_path.write_text(
        yaml_path.read_text().replace("/tmp/owrap-dev", str(first_checkout))
    )
    (other / "other.yaml").write_text(
        "schema_version: 1\nkind: repository\nid: other\n"
        f"main: memory.md\ncheckout: {second_checkout}\n"
    )
    (other / "memory.md").write_text("# Other\n")
    project_yaml = project / "owrap.yaml"
    project_yaml.write_text(
        project_yaml.read_text().replace(
            "repositories: [owrap-dev]", "repositories: [owrap-dev, other]",
        )
    )
    target = resolve_memory_target({
        "target_kind": "project", "project_id": "owrap",
        "subproject_id": "migration", "workspace": "test",
    })

    selected = touched_repository_paths(target, [str(source)], "test")

    assert selected == {"other": other / "memory.md"}


def test_explicit_status_skips_concurrent_project_change(tmp_path, monkeypatch):
    _, project, _ = _records(tmp_path, monkeypatch)
    project_path = project / "migration.md"
    old_snapshot = project_path.read_bytes()
    project_path.write_text(project_path.read_text() + "\n## Status\nNewer state.\n")
    runner = CtxWorkerRunner()

    runner._merge_record_project(
        "## Status\nOlder state.\n", project_path, old_snapshot,
    )

    text = project_path.read_text()
    assert "Newer state." in text
    assert "Older state." not in text


def test_older_transcript_does_not_update_newer_records(tmp_path, monkeypatch):
    _, project, repo = _records(tmp_path, monkeypatch)
    project_path = project / "migration.md"
    repo_path = repo / "memory.md"
    runner = CtxWorkerRunner()

    runner._merge_record_project(
        "## Status\nStale status.\n", project_path,
        project_path.read_bytes(), event_ns=1,
    )
    runner._merge_record_repository(
        "## Components\n- stale.py — old role\n", repo_path, event_ns=1,
    )

    assert "Stale status." not in project_path.read_text()
    assert "stale.py" not in repo_path.read_text()


def test_concurrent_repository_change_blocks_stale_merge(tmp_path, monkeypatch):
    _, _, repo = _records(tmp_path, monkeypatch)
    path = repo / "memory.md"
    snapshot = path.read_bytes()
    path.write_text(path.read_text() + "\n## Components\n- newer.py — owner\n")

    CtxWorkerRunner()._merge_record_repository(
        "## Components\n- stale.py — old role\n", path,
        snapshot=snapshot,
    )

    assert "newer.py" in path.read_text()
    assert "stale.py" not in path.read_text()


def test_new_repository_fact_replaces_superseded_subject(tmp_path, monkeypatch):
    _, _, repo = _records(tmp_path, monkeypatch)
    path = repo / "memory.md"
    path.write_text(path.read_text() + "\n## Components\n- module.py — old role\n")

    CtxWorkerRunner()._merge_record_repository(
        "## Components\n- module.py — new role\n", path,
        event_ns=time.time_ns() + 1_000_000_000,
    )

    text = path.read_text()
    assert "module.py — new role" in text
    assert "module.py — old role" not in text


def test_explicit_updr_accepts_no_new_facts():
    runner = CtxWorkerRunner()

    assert runner._validate_output(
        "# No updates\n", do_context=False, do_protocol=True,
    )


def test_ctx_dispatch_routes_subproject_override_and_touched_repo(
    tmp_path, monkeypatch,
):
    root, project, repo = _records(tmp_path, monkeypatch)
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    source = checkout / "module.py"
    source.write_text("pass\n")
    yaml_path = repo / "owrap-dev.yaml"
    yaml_path.write_text(
        yaml_path.read_text().replace("/tmp/owrap-dev", str(checkout))
    )
    session_path = tmp_path / "session"
    session_path.write_text(
        "target_kind=project\nproject_id=owrap\n"
        "subproject_id=\nworkspace=test\n"
    )
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(json.dumps({
        "type": "assistant", "message": {
            "role": "assistant", "content": [
                {"type": "text", "text": "Updated module.py"},
            ],
        },
    }) + "\n")
    ctx_dir = tmp_path / "ctx"
    monkeypatch.setattr(
        "owrap.commands.context_manager.session_file", lambda sid: session_path,
    )
    monkeypatch.setattr(
        "owrap.commands.context_manager.session_ctx_dir",
        lambda sid, cid: ctx_dir,
    )
    monkeypatch.setattr(
        "owrap.commands.context_manager.session_ctx_transcript_path",
        lambda sid, cid: ctx_dir / "transcript.txt",
    )
    monkeypatch.setattr(
        "owrap.commands.context_manager.context_path",
        lambda sid: tmp_path / "context.md",
    )
    runner = CtxWorkerRunner()
    monkeypatch.setattr(runner, "_read_window_state", lambda sid, cid: {})
    monkeypatch.setattr(runner, "_write_window_state", lambda *args: None)
    monkeypatch.setattr(
        runner, "_load_touched_entries",
        lambda sid, cid: [{"path": str(source), "note": ""}],
    )
    monkeypatch.setattr(runner, "_clear_touched_entries", lambda *args: None)
    monkeypatch.setattr(
        runner, "_run_dispatch_attempt",
            lambda *args: (
                0, "# Subproject: migration\n## Status\nMigration running.\n"
            "# Repository: owrap-dev\n## Components\n"
            "- module.py — parser\n",
            {"idled_out": False, "stdout": ""},
        ),
    )

    rc, reason, model = runner._dispatch(
        "sid", "cid", str(transcript), {"docs_root": str(root)},
        do_context=False, do_protocol=True,
        subproject_override="migration",
    )

    assert rc == 0
    prompt = (ctx_dir / "input.md").read_text()
    assert "# Repository: owrap-dev" in prompt
    assert "Migration running." in (project / "migration.md").read_text()
    assert "module.py — parser" in (repo / "memory.md").read_text()


def test_normalize_identity_kind_aliases_only_the_singular_forms():
    assert normalize_identity_kind("proj") == "project"
    assert normalize_identity_kind("sub") == "subproject"
    assert normalize_identity_kind("repo") == "repository"
    # "subs"/"repos" mean multiple — never aliases for a single target.
    assert normalize_identity_kind("subs") == "subs"
    assert normalize_identity_kind("repos") == "repos"
    assert normalize_identity_kind("project") == "project"


def test_count_bullets_counts_only_entries_under_the_heading(tmp_path):
    path = tmp_path / "main.md"
    path.write_text(
        "# Demo\n\n## Decisions\n\n- first\n- second\n\n"
        "## Notes\n\n- not counted\n"
    )
    assert count_bullets(path, "## Decisions") == 2


def test_count_bullets_is_zero_for_missing_file_or_heading(tmp_path):
    missing = tmp_path / "missing.md"
    assert count_bullets(missing, "## Decisions") == 0

    path = tmp_path / "main.md"
    path.write_text("# Demo\n\n## Notes\n\n- a note\n")
    assert count_bullets(path, "## Decisions") == 0
