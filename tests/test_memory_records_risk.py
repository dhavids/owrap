import yaml

from owrap.utils.memory import records as records_mod
from owrap.utils.memory.records import is_high_risk_session, resolve_memory_target


def _write_project(tmp_path, record):
    directory = tmp_path / "projects" / "myproj"
    directory.mkdir(parents=True)
    (directory / "main.md").write_text("## Overview\n")
    full = {
        "kind": "project", "id": "myproj", "schema_version": 1,
        "main": "main.md", "repositories": [], "subprojects": {},
        **record,
    }
    (directory / "myproj.yaml").write_text(yaml.safe_dump(full))


def _session(subproject_id=""):
    return {
        "target_kind": "project", "project_id": "myproj",
        "subproject_id": subproject_id,
    }


def test_project_with_no_risk_field_resolves_low_risk(tmp_path, monkeypatch):
    monkeypatch.setattr(records_mod, "docs_root", lambda workspace="": tmp_path)
    _write_project(tmp_path, {})

    target = resolve_memory_target(_session())

    assert target.high_risk is False


def test_project_marked_high_risk_resolves_high_risk(tmp_path, monkeypatch):
    monkeypatch.setattr(records_mod, "docs_root", lambda workspace="": tmp_path)
    _write_project(tmp_path, {"risk": "high"})

    target = resolve_memory_target(_session())

    assert target.high_risk is True


def test_subproject_marked_high_risk_does_not_affect_the_project_itself(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(records_mod, "docs_root", lambda workspace="": tmp_path)
    _write_project(tmp_path, {
        "subprojects": {"docs": {"file": "docs.md", "risk": "high"}},
    })
    (tmp_path / "projects" / "myproj" / "docs.md").write_text("## Overview\n")

    main_target = resolve_memory_target(_session())
    sub_target = resolve_memory_target(_session("docs"))

    assert main_target.high_risk is False
    assert sub_target.high_risk is True


def test_high_risk_project_escalates_a_low_risk_subproject(tmp_path, monkeypatch):
    """
    A subproject can't de-escalate below its own project's risk --
    marking the project high-risk covers every subproject under it,
    even one with no risk field of its own.
    """
    monkeypatch.setattr(records_mod, "docs_root", lambda workspace="": tmp_path)
    _write_project(tmp_path, {
        "risk": "high",
        "subprojects": {"docs": {"file": "docs.md"}},
    })
    (tmp_path / "projects" / "myproj" / "docs.md").write_text("## Overview\n")

    target = resolve_memory_target(_session("docs"))

    assert target.high_risk is True


def test_is_high_risk_session_matches_the_resolved_target(tmp_path, monkeypatch):
    monkeypatch.setattr(records_mod, "docs_root", lambda workspace="": tmp_path)
    _write_project(tmp_path, {"risk": "high"})

    assert is_high_risk_session(_session()) is True


def test_is_high_risk_session_false_for_an_unresolvable_session():
    assert is_high_risk_session({"target_kind": "project"}) is False
