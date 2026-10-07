from pathlib import Path

from owrap.session.orientation import print_orientation
from owrap.utils.memory.records import MemoryTarget


def _project_target(project_id, subproject_id="", project_path=None):
    return MemoryTarget(
        kind="project", project_id=project_id, subproject_id=subproject_id,
        project_path=project_path or Path("/tmp/main.md"),
        repository_ids=(), repository_paths=(),
    )


def _repository_target(repository_id):
    return MemoryTarget(
        kind="repository", project_id="", subproject_id="",
        project_path=None,
        repository_ids=(repository_id,),
        repository_paths=(Path("/tmp/memory.md"),),
    )


def test_self_referential_project_gets_self_md_reload_note(
    monkeypatch, capsys, tmp_path,
):
    self_path = tmp_path / "self.md"
    monkeypatch.setattr(
        "owrap.utils.paths.resolve_general_instruction_path", lambda sid: None,
    )
    monkeypatch.setattr(
        "owrap.utils.paths.get_self_path", lambda: self_path,
    )
    print_orientation(
        "sid1", target=_project_target("owrap"),
    )
    out = capsys.readouterr().out
    assert "RELOAD" in out
    assert str(self_path) in out
    assert "self-referential session" in out


def test_non_owrap_project_gets_no_self_md_reload_note(monkeypatch, capsys):
    monkeypatch.setattr(
        "owrap.utils.paths.resolve_general_instruction_path", lambda sid: None,
    )
    monkeypatch.setattr(
        "owrap.utils.paths.get_self_path",
        lambda: (_ for _ in ()).throw(AssertionError("should not be called")),
    )
    print_orientation(
        "sid1", target=_project_target("myproject"),
    )
    out = capsys.readouterr().out
    assert "RELOAD" not in out


def test_repository_only_session_gets_no_self_md_reload_note(monkeypatch, capsys):
    monkeypatch.setattr(
        "owrap.utils.paths.resolve_general_instruction_path", lambda sid: None,
    )
    monkeypatch.setattr(
        "owrap.utils.paths.get_self_path",
        lambda: (_ for _ in ()).throw(AssertionError("should not be called")),
    )
    print_orientation(
        "sid1", target=_repository_target("owrap"),
    )
    out = capsys.readouterr().out
    assert "RELOAD" not in out


def test_owrap_subproject_still_gets_self_md_reload_note(monkeypatch, capsys, tmp_path):
    self_path = tmp_path / "self.md"
    monkeypatch.setattr(
        "owrap.utils.paths.resolve_general_instruction_path", lambda sid: None,
    )
    monkeypatch.setattr(
        "owrap.utils.paths.get_self_path", lambda: self_path,
    )
    print_orientation(
        "sid1", target=_project_target("owrap", subproject_id="migration"),
    )
    out = capsys.readouterr().out
    assert str(self_path) in out
