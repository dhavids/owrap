import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from owrap.session.workflow import SessionWorkflow
from owrap.utils.session.resolver import _parse, session_file


def _git(path: Path, *args: str):
    subprocess.run(["git", "-C", str(path), *args], check=True,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)


@pytest.fixture
def workflow_home(tmp_path, monkeypatch):
    sessions = tmp_path / "sessions"
    sessions.mkdir(exist_ok=True)
    monkeypatch.setattr("owrap.utils.session.resolver.SESSIONS_DIR", sessions)
    monkeypatch.setattr(
        "owrap.utils.session.resolver.BY_CCSID_DIR",
        sessions / "by_ccsid",
    )
    monkeypatch.setattr(
        "owrap.utils.session.resolver.BY_OPENCODE_RUN_ID_DIR",
        sessions / "by_opencode_run_id",
    )
    monkeypatch.setattr(
        "owrap.utils.session.resolver.BY_CODEX_SESSION_ID_DIR",
        sessions / "by_codex_session_id",
    )
    monkeypatch.setattr("owrap.utils.paths.SESSION_DIR", tmp_path)
    monkeypatch.setattr("owrap.utils.paths.SESSIONS_DIR", sessions)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(
        "owrap.session.workflow.get_workspace_config",
        lambda _: {"workspace": str(workspace)},
    )
    monkeypatch.setattr(
        "owrap.session.workflow._read_config",
        lambda: {"default_workspace": "test"},
    )
    return sessions, workspace


def _parent(sessions: Path, repo_ids: list[str] | None = None):
    values = {
        "session_id": "parent", "workspace": "test",
        "target_kind": "project", "project_id": "demo",
        "subproject_id": "feature", "repositories": json.dumps(repo_ids or []),
    }
    path = session_file("parent")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(f"{key}={value}" for key, value in values.items()) + "\n"
    )


def test_spawn_inherits_target_and_collapse_preserves_parent_context(
    workflow_home, monkeypatch,
):
    sessions, workspace = workflow_home
    _parent(sessions, ["code"])
    monkeypatch.setenv("SESSION_ID", "parent")
    child = SessionWorkflow().create("spawn", "trial")
    sid = child["session_id"]
    assert child["parent_session_id"] == "parent"
    assert child["subproject_id"] == "feature"
    assert json.loads(child["repositories"]) == ["code"]
    assert not (workspace / "branches").exists()

    parent_context = sessions / "parent" / "context.md"
    child_context = sessions / sid / "context.md"
    parent_context.parent.mkdir(exist_ok=True)
    child_context.parent.mkdir(exist_ok=True)
    parent_context.write_text(
        "# Context\n\n## Focus\n\nKeep parent focus.\n\n"
        "## Decisions\n\n- Existing decision\n"
    )
    child_context.write_text(
        "# Context\n\n## Focus\n\nChild focus.\n\n"
        "## Decisions\n\n- Existing decision\n- New decision\n"
    )
    preview = SessionWorkflow().collapse(sid)
    assert preview["entries"]["## Decisions"] == ["- New decision"]
    assert "New decision" not in parent_context.read_text()
    SessionWorkflow().collapse(sid, apply=True)
    merged = parent_context.read_text()
    assert "Keep parent focus." in merged
    assert "Child focus." not in merged
    assert merged.count("Existing decision") == 1
    assert "New decision" in merged
    assert _parse(session_file(sid))["collapsed_into"] == "parent"


def test_temp_has_no_parent_or_project_and_creates_no_checkout(workflow_home):
    from owrap.utils.paths import context_path, session_dir, session_log

    sessions, workspace = workflow_home
    temp = SessionWorkflow().create("temp")
    assert temp["session_name"] == f"temp-{temp['session_id']}"
    assert "parent_session_id" not in temp
    assert "project_id" not in temp
    docs = sessions / temp["session_id"]
    assert session_dir(temp["session_id"]) == docs
    assert context_path(temp["session_id"]) == docs / "context.md"
    assert context_path(temp["session_id"]).exists()
    assert session_log(Path("/test/run/log.md"), temp["session_id"]) == (
        docs / "run" / "log.md"
    )
    assert not (sessions.parent / "tmp" / "sessions").exists()
    assert session_file(temp["session_id"]).exists()
    assert not (workspace / "branches").exists()
    with pytest.raises(ValueError, match="no parent"):
        SessionWorkflow().collapse(temp["session_id"])


def test_stat_identifies_temp_session(workflow_home, monkeypatch, capsys):
    from owrap.session.stat import StatRunner

    sessions, _ = workflow_home
    _parent(sessions)
    temp = SessionWorkflow().create("temp")
    monkeypatch.setattr("owrap.session.stat.SESSIONS_DIR", sessions)
    monkeypatch.setattr("owrap.utils.dispatch.pool.get_pool", lambda: [])

    StatRunner(None).run(SimpleNamespace(filter=None))
    output = capsys.readouterr().out
    assert f"  {temp['session_id']}\n    type:     temp" in output
    assert "  parent\n    type:     normal" in output
    assert "project:  demo\n    sub:      feature" in output
    assert "research:" not in output


def test_branch_worktree_merge_then_collapse(workflow_home, tmp_path, monkeypatch):
    sessions, workspace = workflow_home
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    _git(checkout, "init", "-b", "main")
    _git(checkout, "config", "user.name", "Test")
    _git(checkout, "config", "user.email", "test@example.com")
    (checkout / "README.md").write_text("base\n")
    _git(checkout, "add", "README.md")
    _git(checkout, "commit", "-m", "base")
    root = workspace / "docs" / "research"
    record_dir = root / "repositories" / "code"
    record_dir.mkdir(parents=True)
    (record_dir / "code.yaml").write_text(
        "schema_version: 1\nkind: repository\nid: code\n"
        f"checkout: {checkout}\nmain: main.md\n"
    )
    (record_dir / "main.md").write_text("# Code\n")
    monkeypatch.setattr("owrap.session.workflow.docs_root", lambda _: root)
    _parent(sessions, ["code"])
    monkeypatch.setenv("SESSION_ID", "parent")

    child = SessionWorkflow().create("branch", "trial")
    sid = child["session_id"]
    entry = json.loads(child["branch_worktrees"])["code"]
    worktree = Path(entry["path"])
    assert worktree == workspace / "branches" / sid / "code"
    assert (worktree / "README.md").read_text() == "base\n"
    (worktree / "README.md").write_text("branch\n")
    _git(worktree, "add", "README.md")
    _git(worktree, "commit", "-m", "branch change")
    assert (checkout / "README.md").read_text() == "base\n"

    preview = SessionWorkflow().merge_branch(sid)
    assert not preview["applied"]
    assert (checkout / "README.md").read_text() == "base\n"
    with pytest.raises(ValueError, match="merge branch code"):
        SessionWorkflow().collapse(sid)
    SessionWorkflow().merge_branch(sid, apply=True)
    assert (checkout / "README.md").read_text() == "branch\n"
    assert worktree.exists()
    SessionWorkflow().collapse(sid, apply=True)
    assert _parse(session_file(sid))["collapsed_into"] == "parent"
    cleanup = SessionWorkflow().cleanup_branch(sid)
    assert not cleanup["applied"]
    assert worktree.exists()
    SessionWorkflow().cleanup_branch(sid, apply=True)
    assert not worktree.exists()
    assert not (workspace / "branches" / sid).exists()


def test_branch_rejects_dirty_parent_before_creating_folders(
    workflow_home, tmp_path, monkeypatch,
):
    sessions, workspace = workflow_home
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    _git(checkout, "init", "-b", "main")
    _git(checkout, "config", "user.name", "Test")
    _git(checkout, "config", "user.email", "test@example.com")
    (checkout / "README.md").write_text("base\n")
    _git(checkout, "add", "README.md")
    _git(checkout, "commit", "-m", "base")
    (checkout / "README.md").write_text("dirty\n")
    root = workspace / "docs" / "research"
    record_dir = root / "repositories" / "code"
    record_dir.mkdir(parents=True)
    (record_dir / "code.yaml").write_text(
        "schema_version: 1\nkind: repository\nid: code\n"
        f"checkout: {checkout}\nmain: main.md\n"
    )
    monkeypatch.setattr("owrap.session.workflow.docs_root", lambda _: root)
    _parent(sessions, ["code"])
    monkeypatch.setenv("SESSION_ID", "parent")

    with pytest.raises(ValueError, match="uncommitted changes"):
        SessionWorkflow().create("branch")
    assert not (workspace / "branches").exists()
