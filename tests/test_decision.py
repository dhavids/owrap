import pytest

from owrap.cli import main as cli_main
from owrap.kind.entry.decision import Decision


def _project(tmp_path, monkeypatch):
    root = tmp_path / "research"
    project = root / "projects" / "proj"
    project.mkdir(parents=True)
    (project / "proj.yaml").write_text(
        "schema_version: 1\nkind: project\nid: proj\nmain: main.md\n",
    )
    (project / "main.md").write_text("# proj\n\n## Decisions\n\n\n## Notes\n")
    monkeypatch.setattr(
        "owrap.utils.memory.records.get_workspace_config",
        lambda workspace: {"docs_root": str(root)},
    )
    return project


@pytest.fixture
def decision_setup(tmp_path, monkeypatch):
    project = _project(tmp_path, monkeypatch)
    sessions = tmp_path / "sessions"
    sessions.mkdir(exist_ok=True)
    sfile = sessions / "abc123.session"
    sfile.write_text(
        "session_id=abc123\ntarget_kind=project\nproject_id=proj\nworkspace=test\n",
    )
    monkeypatch.setattr("owrap.actions.resolve_session_or_exit", lambda t: "abc123")
    monkeypatch.setattr("owrap.actions.session_file", lambda s: sfile)
    return project


def _decision_lines(project):
    text = project.joinpath("main.md").read_text()
    body = text.split("## Decisions\n\n", 1)[1].split("\n\n## Notes", 1)[0]
    return [line for line in body.splitlines() if line.startswith("- ")]


def test_add_then_remove_round_trip(decision_setup):
    Decision().add("abc123", "Ship it")
    assert len(_decision_lines(decision_setup)) == 1
    Decision().remove("abc123", "1")
    assert _decision_lines(decision_setup) == []


def test_add_missing_text_shows_usage_not_a_crash(decision_setup, capsys):
    with pytest.raises(SystemExit) as exc:
        Decision().add("abc123", None)
    assert exc.value.code == 2
    assert "Usage: owrap decision add" in capsys.readouterr().out


def test_clear_removes_all_entries(decision_setup):
    Decision().add("abc123", "one")
    Decision().add("abc123", "two")
    Decision().clear("abc123")
    assert _decision_lines(decision_setup) == []


def test_cli_decision_add_round_trip(decision_setup, capsys):
    cli_main(["decision", "add", "abc123", "Keep the dev/live split"])
    assert "Keep the dev/live split" in capsys.readouterr().out
    assert len(_decision_lines(decision_setup)) == 1


# Decision._default_get -- count + prune-threshold escalation

def test_default_get_plain_count_below_notice_threshold(
    decision_setup, monkeypatch, capsys,
):
    monkeypatch.setenv("SESSION_ID", "abc123")
    for i in range(3):
        Decision().add("abc123", f"decision {i}")
    Decision()._default_get()
    out = capsys.readouterr().out
    assert "decisions: 3 (" in out
    assert "consider pruning" not in out
    assert "PRUNE NOW" not in out


def test_default_get_notice_at_threshold(decision_setup, monkeypatch, capsys):
    monkeypatch.setenv("SESSION_ID", "abc123")
    for i in range(35):
        Decision().add("abc123", f"decision {i}")
    capsys.readouterr()
    Decision()._default_get()
    out = capsys.readouterr().out
    assert "decisions: 35 (" in out
    assert "consider pruning (35+)" in out
    assert "PRUNE NOW" not in out


def test_default_get_escalates_past_prune_threshold(
    decision_setup, monkeypatch, capsys,
):
    monkeypatch.setenv("SESSION_ID", "abc123")
    for i in range(40):
        Decision().add("abc123", f"decision {i}")
    capsys.readouterr()
    Decision()._default_get()
    out = capsys.readouterr().out
    assert "decisions: 40 (" in out
    assert "PRUNE NOW (40+)" in out
    assert "consider pruning" not in out
