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


def test_repository_only_start_ignores_default_research(
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
             "default_research": "legacy", "max_servers": 1,
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
    assert mock_manager.research == ""


def test_start_context_uses_recorded_research(mock_manager, monkeypatch, tmp_path):
    session_path = tmp_path / "legacy.session"
    context_research = []
    monkeypatch.setattr(resolver, "session_file", lambda sid: session_path)
    monkeypatch.setattr("owrap.session.start._sf", lambda sid: session_path)
    for method in (
        "create_context", "_housekeeping", "refresh_context_plan",
        "start_watchdog",
    ):
        setattr(mock_manager, method, MagicMock())
    mock_manager.create_context.side_effect = (
        lambda: context_research.append(mock_manager.research)
    )

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
                session_id="legacy", research="owrap",
            )

    assert exc.value.code == 0
    assert resolver._parse(session_path)["research"] == "owrap"
    assert context_research == ["owrap"]


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
