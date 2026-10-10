import pytest

from owrap.actions import Actions, dispatch
from owrap.cli import main as cli_main
from owrap.kind.entry import Entry
from owrap.kind.entry.todo import Todo


# Actions: _usage/_ok entry points

class _ToyKind(Actions):
    kind = "toy"
    usage = {
        "add": {
            "usage": "<a>",
            "args": [("a", "the thing to add")],
            "examples": ["x"],
        },
    }
    messages = {"add": "did {thing}"}

    def add(self, a=None):
        if a is None:
            self._usage("add")
        self._ok("add", thing=a)


def test_usage_builds_kind_action_prefix(capsys):
    with pytest.raises(SystemExit) as exc:
        _ToyKind().add(None)
    out = capsys.readouterr().out
    assert exc.value.code == 2
    assert "Usage: owrap toy add <a>" in out
    assert "a  the thing to add" in out
    assert "owrap toy add x" in out


def test_ok_formats_registered_message(capsys):
    _ToyKind().add("stuff")
    assert capsys.readouterr().out.strip() == "did stuff"


# dispatch(): None-padding for a missing trailing argument

def test_dispatch_pads_missing_trailing_args_with_none():
    calls = []

    class _Padded(Actions):
        kind = "padded"

        def add(self, a, b=None):
            calls.append((a, b))

    dispatch({"padded": _Padded}, "padded", "add", "only-a")
    assert calls == [("only-a", None)]


# Entry: shared target resolution

class _ToyDoc(Entry):
    kind = "toydoc"


def test_resolve_target_no_target_no_session_fails(monkeypatch, capsys):
    monkeypatch.delenv("SESSION_ID", raising=False)
    with pytest.raises(SystemExit) as exc:
        _ToyDoc()._resolve_target(None)
    assert exc.value.code == 2
    assert "no target given" in capsys.readouterr().out


def test_resolve_target_repository_only_uses_noun(tmp_path, monkeypatch, capsys):
    repo = tmp_path / "research" / "repositories" / "myrepo"
    repo.mkdir(parents=True)
    (repo / "myrepo.yaml").write_text(
        "schema_version: 1\nkind: repository\nid: myrepo\n"
        "main: memory.md\ncheckout: /tmp/myrepo\n",
    )
    (repo / "memory.md").write_text("# Architecture\n")
    monkeypatch.setattr(
        "owrap.utils.memory.records.get_workspace_config",
        lambda workspace: {"docs_root": str(tmp_path / "research")},
    )
    sessions = tmp_path / "sessions"
    sessions.mkdir(exist_ok=True)
    sfile = sessions / "abc123.session"
    sfile.write_text(
        "session_id=abc123\ntarget_kind=repository\nrepository_id=myrepo\n"
        "workspace=test\n",
    )
    monkeypatch.setattr("owrap.actions.resolve_session_or_exit", lambda token: "abc123")
    monkeypatch.setattr("owrap.actions.session_file", lambda s: sfile)

    with pytest.raises(SystemExit) as exc:
        _ToyDoc()._resolve_target("abc123", noun="widgets")
    assert exc.value.code == 2
    assert "no project widgets" in capsys.readouterr().out


# Todo: the actual goal-editing behavior, through the new structure

def _project(tmp_path, monkeypatch, goals_body=""):
    root = tmp_path / "research"
    project = root / "projects" / "proj"
    project.mkdir(parents=True)
    (project / "proj.yaml").write_text(
        "schema_version: 1\nkind: project\nid: proj\nmain: main.md\n",
    )
    (project / "main.md").write_text(
        f"# proj\n\n## Goals\n\n{goals_body}\n## Notes\n",
    )
    monkeypatch.setattr(
        "owrap.utils.memory.records.get_workspace_config",
        lambda workspace: {"docs_root": str(root)},
    )
    return project


@pytest.fixture
def todo_setup(tmp_path, monkeypatch):
    project = _project(tmp_path, monkeypatch)
    sessions = tmp_path / "sessions"
    sessions.mkdir(exist_ok=True)
    sfile = sessions / "abc123.session"
    sfile.write_text(
        "session_id=abc123\ntarget_kind=project\nproject_id=proj\nworkspace=test\n",
    )
    monkeypatch.setattr("owrap.actions.resolve_session_or_exit", lambda token: "abc123")
    monkeypatch.setattr("owrap.actions.session_file", lambda s: sfile)
    return project


def _goal_lines(project):
    text = project.joinpath("main.md").read_text()
    body = text.split("## Goals\n\n", 1)[1].split("\n\n## Notes", 1)[0]
    return [line[2:] for line in body.splitlines() if line.startswith("- ")]


def test_add_then_done_preserves_order_and_marks_done(todo_setup):
    Todo().add("abc123", "a", None)
    Todo().add("abc123", "b", None)
    Todo().done("abc123", "1")
    assert _goal_lines(todo_setup) == ["[x] a", "[ ] b"]


def test_add_missing_text_shows_usage_not_a_crash(todo_setup, capsys):
    with pytest.raises(SystemExit) as exc:
        Todo().add("abc123", None, None)
    assert exc.value.code == 2
    assert "Usage: owrap todo add" in capsys.readouterr().out


def test_update_replaces_in_place_keeping_done_state(todo_setup):
    Todo().add("abc123", "a", None)
    Todo().done("abc123", "1")
    Todo().update("abc123", "1", "replaced")
    assert _goal_lines(todo_setup) == ["[x] replaced"]


def test_remove_deletes_outright(todo_setup):
    Todo().add("abc123", "a", None)
    Todo().add("abc123", "b", None)
    Todo().remove("abc123", "1")
    assert _goal_lines(todo_setup) == ["[ ] b"]


def test_clear_removes_only_done_items(todo_setup):
    Todo().add("abc123", "a", None)
    Todo().add("abc123", "b", None)
    Todo().done("abc123", "1")
    Todo().clear("abc123")
    assert _goal_lines(todo_setup) == ["[ ] b"]


def test_done_next_selects_first_pending(todo_setup):
    Todo().add("abc123", "a", None)
    Todo().add("abc123", "b", None)
    Todo().done("abc123", "1")
    Todo().done("abc123", "next")
    assert _goal_lines(todo_setup) == ["[x] a", "[x] b"]


def test_done_ambiguous_phrase_fails(todo_setup, capsys):
    Todo().add("abc123", "fix the widget", None)
    Todo().add("abc123", "fix the gadget", None)
    with pytest.raises(SystemExit) as exc:
        Todo().done("abc123", "fix the")
    assert exc.value.code == 2
    assert "goal selector must match one goal" in capsys.readouterr().out


# cli.py: the kind-first entry point

def test_cli_todo_add_round_trip(todo_setup, capsys):
    cli_main(["todo", "add", "abc123", "first item"])
    assert "first item" in capsys.readouterr().out
    assert _goal_lines(todo_setup) == ["[ ] first item"]


def test_cli_missing_args_shows_usage(todo_setup, capsys):
    with pytest.raises(SystemExit) as exc:
        cli_main(["todo", "add", "abc123"])
    assert exc.value.code == 2
    assert "Usage: owrap todo add" in capsys.readouterr().out


def test_cli_unknown_kind_fails_cleanly(capsys):
    with pytest.raises(SystemExit) as exc:
        cli_main(["ghost", "add", "x", "y"])
    assert exc.value.code == 2
    assert "ERROR: no such kind 'ghost'" in capsys.readouterr().out


def test_cli_kind_with_no_action_shows_full_help(capsys):
    with pytest.raises(SystemExit) as exc:
        cli_main(["todo"])
    out = capsys.readouterr().out
    assert exc.value.code == 2
    assert "Usage: owrap todo add" in out
    assert "Usage: owrap todo done" in out
