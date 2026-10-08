import json
from unittest.mock import MagicMock, patch

import pytest

from owrap.session.start import StartRunner
from owrap.utils.session import resolver


def test_project_identity_preserves_legacy_fields(monkeypatch, tmp_path):
    session_path = tmp_path / "abc123.session"
    session_path.write_text("session_id=abc123\nresearch=owrap\narea=main\n")
    monkeypatch.setattr(resolver, "session_file", lambda sid: session_path)

    resolver.set_session_identity(
        "abc123", project_id="owrap", subproject_id="migration",
        repositories=["owrap-dev", "owrap-dev"], branch_parent="main",
        branch_repository="owrap-dev", branch_ref="trial/migration",
    )

    data = resolver._parse(session_path)
    assert data["target_kind"] == "project"
    assert data["project_id"] == "owrap"
    assert data["subproject_id"] == "migration"
    assert data["branch_parent"] == "main"
    assert data["branch_repository"] == "owrap-dev"
    assert data["branch_ref"] == "trial/migration"
    assert json.loads(data["repositories"]) == ["owrap-dev"]
    assert data["research"] == "owrap"
    assert data["area"] == "main"


def test_repository_only_identity_clears_project_fields(monkeypatch, tmp_path):
    session_path = tmp_path / "abc123.session"
    session_path.write_text("session_id=abc123\n")
    monkeypatch.setattr(resolver, "session_file", lambda sid: session_path)

    resolver.set_session_identity(
        "abc123", project_id="owrap", repositories=["owrap-dev"],
    )
    resolver.set_session_identity("abc123", repository_id="owrap-dev")

    data = resolver._parse(session_path)
    assert data["target_kind"] == "repository"
    assert data["project_id"] == ""
    assert data["repository_id"] == "owrap-dev"
    assert json.loads(data["repositories"]) == ["owrap-dev"]


def test_repository_only_start_clears_research_and_area(
    mock_manager, monkeypatch, tmp_path,
):
    session_path = tmp_path / "repo001.session"
    monkeypatch.setattr(resolver, "session_file", lambda sid: session_path)
    monkeypatch.setattr("owrap.session.start._sf", lambda sid: session_path)
    for method in (
        "create_context", "_housekeeping", "refresh_context_plan",
        "start_watchdog",
    ):
        setattr(mock_manager, method, MagicMock())

    with patch("owrap.session.start.SESSION_DIR", tmp_path), \
         patch("owrap.session.start._read_config", return_value={
             "max_servers": 1,
         }), \
         patch("owrap.session.start.print_orientation"), \
         patch("owrap.utils.dispatch.pool._pool_active", return_value=True), \
         patch("owrap.utils.dispatch.pool.ensure_min_servers"), \
         patch("owrap.utils.dispatch.pool._ensure_daemon"):
        with pytest.raises(SystemExit) as exc:
            StartRunner(mock_manager).run(
                session_id="repo001", repository_id="owrap-dev",
            )

    data = resolver._parse(session_path)
    assert exc.value.code == 0
    assert data["target_kind"] == "repository"
    assert data["repository_id"] == "owrap-dev"
    assert data.get("research") == ""
    assert data.get("area") == ""


def test_start_with_bare_name_resolves_to_project(
    mock_manager, monkeypatch, tmp_path,
):
    """
    'owrap start <name>' with no --project/--repository treats the bare
    name as a project id, creating it if it doesn't exist yet.
    """
    session_path = tmp_path / "legacy.session"
    monkeypatch.setattr(resolver, "session_file", lambda sid: session_path)
    monkeypatch.setattr("owrap.session.start._sf", lambda sid: session_path)
    for method in (
        "create_context", "_housekeeping", "refresh_context_plan",
        "start_watchdog",
    ):
        setattr(mock_manager, method, MagicMock())
    root = tmp_path / "research"

    with patch("owrap.session.start.SESSION_DIR", tmp_path), \
         patch("owrap.session.start._read_config", return_value={
             "max_servers": 1, "default_workspace": "test",
         }), \
         patch(
             "owrap.session.start.get_workspace_config",
             lambda name: {"docs_root": str(root)} if name == "test" else {},
         ), \
         patch(
             "owrap.utils.memory.records.get_workspace_config",
             lambda name: {"docs_root": str(root)} if name == "test" else {},
         ), \
         patch("owrap.session.start.print_orientation"), \
         patch("owrap.utils.dispatch.pool._pool_active", return_value=True), \
         patch("owrap.utils.dispatch.pool.ensure_min_servers"), \
         patch("owrap.utils.dispatch.pool._ensure_daemon"):
        with pytest.raises(SystemExit) as exc:
            StartRunner(mock_manager).run(
                session_id="legacy", project_name="owrap",
            )

    assert exc.value.code == 0
    data = resolver._parse(session_path)
    assert data["target_kind"] == "project"
    assert data["project_id"] == "owrap"
    assert data.get("research") == ""
    assert data.get("area") == ""
    assert (root / "projects" / "owrap" / "owrap.yaml").exists()
    assert (root / "projects" / "owrap" / "main.md").exists()


def test_start_with_bare_name_and_area_resolves_to_subproject(
    mock_manager, monkeypatch, tmp_path,
):
    """
    'owrap start <name> <sub>' creates or attaches the project and
    creates the subproject under it when it's new.
    """
    session_path = tmp_path / "legacy.session"
    monkeypatch.setattr(resolver, "session_file", lambda sid: session_path)
    monkeypatch.setattr("owrap.session.start._sf", lambda sid: session_path)
    for method in (
        "create_context", "_housekeeping", "refresh_context_plan",
        "start_watchdog",
    ):
        setattr(mock_manager, method, MagicMock())
    root = tmp_path / "research"

    with patch("owrap.session.start.SESSION_DIR", tmp_path), \
         patch("owrap.session.start._read_config", return_value={
             "max_servers": 1, "default_workspace": "test",
         }), \
         patch(
             "owrap.session.start.get_workspace_config",
             lambda name: {"docs_root": str(root)} if name == "test" else {},
         ), \
         patch(
             "owrap.utils.memory.records.get_workspace_config",
             lambda name: {"docs_root": str(root)} if name == "test" else {},
         ), \
         patch("owrap.session.start.print_orientation"), \
         patch("owrap.utils.dispatch.pool._pool_active", return_value=True), \
         patch("owrap.utils.dispatch.pool.ensure_min_servers"), \
         patch("owrap.utils.dispatch.pool._ensure_daemon"):
        with pytest.raises(SystemExit) as exc:
            StartRunner(mock_manager).run(
                session_id="legacy", project_name="scratchproj",
                subproject_name="feature",
            )

    assert exc.value.code == 0
    data = resolver._parse(session_path)
    assert data["target_kind"] == "project"
    assert data["project_id"] == "scratchproj"
    assert data["subproject_id"] == "feature"
    assert data.get("area") == ""
    yaml_path = root / "projects" / "scratchproj" / "scratchproj.yaml"
    assert yaml_path.exists()
    assert "feature" in yaml_path.read_text()
    assert (root / "projects" / "scratchproj" / "feature.md").exists()


@pytest.mark.parametrize("identity", [
    {},
    {"project_id": "owrap", "repository_id": "owrap-dev"},
    {"project_id": "owrap", "branch_parent": "main"},
    {"repository_id": "owrap-dev", "subproject_id": "migration"},
    {"project_id": "owrap", "subproject_id": "migration",
     "branch_parent": "migration"},
    {"project_id": "owrap", "subproject_id": "migration",
     "branch_parent": "main", "branch_repository": "owrap-dev",
     "branch_ref": "trial/migration", "repositories": ["other-repo"]},
])
def test_invalid_identity_does_not_change_session(monkeypatch, tmp_path, identity):
    session_path = tmp_path / "abc123.session"
    original = "session_id=abc123\nresearch=owrap\n"
    session_path.write_text(original)
    monkeypatch.setattr(resolver, "session_file", lambda sid: session_path)

    with pytest.raises(ValueError):
        resolver.set_session_identity("abc123", **identity)

    assert session_path.read_text() == original


def test_refresh_with_bare_name_redirects_to_project(
    mock_manager, monkeypatch, tmp_path,
):
    """
    'owrap refresh <name>' on a session with no project target redirects
    it to that project id, creating the project if it doesn't exist yet.
    """
    from owrap.session.start import RefreshRunner

    session_path = tmp_path / "sessions" / "abc123.session"
    session_path.parent.mkdir(parents=True, exist_ok=True)
    session_path.write_text("session_id=abc123\nworkspace=test\n")
    monkeypatch.setattr(resolver, "session_file", lambda sid: session_path)
    monkeypatch.setattr("owrap.session.start._sf", lambda sid: session_path)
    root = tmp_path / "research"

    with patch("owrap.session.start._read_config", return_value={
        "max_servers": 1, "default_workspace": "test",
    }), \
         patch(
             "owrap.session.start.get_workspace_config",
             lambda name: {"docs_root": str(root)} if name == "test" else {},
         ), \
         patch(
             "owrap.utils.memory.records.get_workspace_config",
             lambda name: {"docs_root": str(root)} if name == "test" else {},
         ), \
         patch("owrap.session.start.print_orientation"), \
         patch("owrap.utils.dispatch.pool._pool_active", return_value=True), \
         patch("owrap.utils.dispatch.pool.ensure_min_servers"), \
         patch("owrap.utils.dispatch.pool._ensure_daemon"), \
         patch.object(mock_manager, "_housekeeping"):
        with pytest.raises(SystemExit) as exc:
            RefreshRunner(mock_manager).run(session_id="abc123", project_name="owrap")

    assert exc.value.code == 0
    data = resolver._parse(session_path)
    assert data["target_kind"] == "project"
    assert data["project_id"] == "owrap"
    assert data.get("research") == ""
    assert (root / "projects" / "owrap" / "owrap.yaml").exists()
    assert mock_manager.context_path.exists()


def test_refresh_repository_session_rejects_research(
    mock_manager, monkeypatch, tmp_path,
):
    from owrap.session.start import RefreshRunner

    session_path = tmp_path / "sessions" / "abc123.session"
    session_path.parent.mkdir(parents=True, exist_ok=True)
    session_path.write_text(
        "session_id=abc123\ntarget_kind=repository\n"
        "repository_id=myrepo\nworkspace=test\n",
    )
    monkeypatch.setattr(resolver, "session_file", lambda sid: session_path)
    monkeypatch.setattr("owrap.session.start._sf", lambda sid: session_path)

    with patch("owrap.session.start._read_config", return_value={
        "max_servers": 1, "default_workspace": "test",
    }), \
         patch("owrap.utils.dispatch.pool._pool_active", return_value=True), \
         patch("owrap.utils.dispatch.pool.ensure_min_servers"), \
         patch("owrap.utils.dispatch.pool._ensure_daemon"), \
         patch.object(mock_manager, "_housekeeping"):
        with pytest.raises(SystemExit) as exc:
            RefreshRunner(mock_manager).run(session_id="abc123", project_name="owrap")

    assert exc.value.code == 2
    data = resolver._parse(session_path)
    assert data["repository_id"] == "myrepo"


def test_start_bare_name_with_explicit_project_is_ambiguous(mock_manager, capsys):
    with pytest.raises(SystemExit) as exc:
        StartRunner(mock_manager).run(
            project_name="bare", project_id="explicit",
        )
    assert exc.value.code == 2
    assert "conflicts" in capsys.readouterr().err


def test_start_bare_name_with_explicit_repository_is_ambiguous(mock_manager, capsys):
    with pytest.raises(SystemExit) as exc:
        StartRunner(mock_manager).run(
            project_name="bare", repository_id="myrepo",
        )
    assert exc.value.code == 2
    assert "conflicts" in capsys.readouterr().err


def test_start_with_zero_args_creates_anonymous_session_without_legacy_file(
    mock_manager, monkeypatch, tmp_path,
):
    """
    With no bare name, no --project/--repository, and no default_research
    fallback, 'owrap start' creates a plain identity-less session and
    never writes a legacy flat projects/<name>.md file.
    """
    session_path = tmp_path / "anon123.session"
    monkeypatch.setattr(resolver, "session_file", lambda sid: session_path)
    monkeypatch.setattr("owrap.session.start._sf", lambda sid: session_path)
    for method in (
        "create_context", "_housekeeping", "refresh_context_plan",
        "start_watchdog",
    ):
        setattr(mock_manager, method, MagicMock())
    docs_root = tmp_path / "research"

    with patch("owrap.session.start.SESSION_DIR", tmp_path), \
         patch("owrap.session.start._read_config", return_value={
             "max_servers": 1, "docs_root": str(docs_root),
         }), \
         patch("owrap.session.start.print_orientation"), \
         patch("owrap.utils.dispatch.pool._pool_active", return_value=True), \
         patch("owrap.utils.dispatch.pool.ensure_min_servers"), \
         patch("owrap.utils.dispatch.pool._ensure_daemon"):
        with pytest.raises(SystemExit) as exc:
            StartRunner(mock_manager).run(session_id="anon123")

    assert exc.value.code == 0
    data = resolver._parse(session_path)
    assert not data.get("target_kind")
    assert not data.get("area")
    assert not docs_root.exists()
