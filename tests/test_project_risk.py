import yaml

from owrap.kind.run import project as project_mod
from owrap.kind.run.project import Project
from owrap.utils.memory import records as records_mod


def _setup(tmp_path, monkeypatch, subprojects=None):
    directory = tmp_path / "projects" / "myproj"
    directory.mkdir(parents=True)
    (directory / "main.md").write_text("## Overview\n")
    record = {
        "kind": "project", "id": "myproj", "schema_version": 1,
        "main": "main.md", "repositories": [],
        "subprojects": subprojects or {},
    }
    (directory / "myproj.yaml").write_text(yaml.safe_dump(record))
    session_path = tmp_path / "sid1.session"
    session_path.write_text(
        "session_id=sid1\ntarget_kind=project\nproject_id=myproj\n"
        "subproject_id=\nworkspace=\n",
    )
    monkeypatch.setattr(
        project_mod, "resolve", lambda mode: ("sid1", session_path, "env"),
    )
    monkeypatch.setattr(project_mod, "docs_root", lambda workspace="": tmp_path)
    monkeypatch.setattr(records_mod, "docs_root", lambda workspace="": tmp_path)
    return directory / "myproj.yaml"


def test_set_risk_high_then_get_risk_reports_high(tmp_path, monkeypatch, capsys):
    yaml_path = _setup(tmp_path, monkeypatch)

    Project().set("risk", "high")
    assert "risk set to high" in capsys.readouterr().out
    assert yaml.safe_load(yaml_path.read_text())["risk"] == "high"

    Project().get("risk")
    assert capsys.readouterr().out.strip() == "high"


def test_project_defaults_to_low_risk(tmp_path, monkeypatch, capsys):
    _setup(tmp_path, monkeypatch)

    Project().get("risk")

    assert capsys.readouterr().out.strip() == "low"


def test_set_risk_on_a_subproject_does_not_affect_the_project(
    tmp_path, monkeypatch, capsys,
):
    directory = tmp_path / "projects" / "myproj"
    yaml_path = _setup(
        tmp_path, monkeypatch, subprojects={"docs": {"file": "docs.md"}},
    )
    (directory / "docs.md").write_text("## Overview\n")
    session_path = tmp_path / "sid1.session"
    session_path.write_text(
        "session_id=sid1\ntarget_kind=project\nproject_id=myproj\n"
        "subproject_id=docs\nworkspace=\n",
    )

    Project().set("risk", "high")
    capsys.readouterr()

    data = yaml.safe_load(yaml_path.read_text())
    assert data.get("risk") != "high"
    assert data["subprojects"]["docs"]["risk"] == "high"
