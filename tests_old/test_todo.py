import pytest

from owrap.commands.todo import TodoRunner


def _project(tmp_path, monkeypatch, goals_body=""):
    """
    Create a minimal project record (<id>.yaml + main.md) with an Overview
    and Notes section flanking Goals, so tests can assert those stay
    untouched by goal edits.
    """
    root = tmp_path / "research"
    project = root / "projects" / "proj"
    project.mkdir(parents=True)
    (project / "proj.yaml").write_text(
        "schema_version: 1\nkind: project\nid: proj\nmain: main.md\n",
    )
    (project / "main.md").write_text(
        f"# proj\n\n## Overview\n\nKeep this.\n\n"
        f"## Goals\n\n{goals_body}\n## Notes\n\nKeep this too.\n",
    )
    monkeypatch.setattr(
        "owrap.utils.memory.records.get_workspace_config",
        lambda workspace: {"docs_root": str(root)},
    )
    return project


def _session(tmp_path, monkeypatch, sid="abc123", **fields):
    sessions = tmp_path / "sessions"
    sessions.mkdir(exist_ok=True)
    body = "".join(f"{k}={v}\n" for k, v in fields.items())
    sfile = sessions / f"{sid}.session"
    sfile.write_text(f"session_id={sid}\n{body}")
    monkeypatch.setattr(
        "owrap.commands.todo.resolve_session_or_exit", lambda token: sid,
    )
    monkeypatch.setattr("owrap.commands.todo.session_file", lambda s: sfile)
    monkeypatch.delenv("SESSION_ID", raising=False)
    return sfile


@pytest.fixture
def todo_setup(tmp_path, monkeypatch):
    project = _project(tmp_path, monkeypatch)
    _session(
        tmp_path, monkeypatch,
        target_kind="project", project_id="proj", workspace="test",
    )
    return project


class TestTodoRunnerAdd:
    def test_no_position_appends_to_end(self, todo_setup):
        TodoRunner().run("abc123", "first item", None)
        TodoRunner().run("abc123", "second item", None)
        assert _goal_lines(todo_setup) == ["[ ] first item", "[ ] second item"]

    def test_bumps_project_last_updated(self, todo_setup):
        import time
        before = time.time()
        TodoRunner().run("abc123", "first item", None)
        import yaml
        record = yaml.safe_load((todo_setup / "proj.yaml").read_text())
        assert record["last_updated"] >= before

    def test_insert_at_position_renumbers(self, todo_setup):
        TodoRunner().run("abc123", "a", None)
        TodoRunner().run("abc123", "b", None)
        TodoRunner().run("abc123", "2", "c")
        goals = _goal_lines(todo_setup)
        assert goals == ["[ ] a", "[ ] c", "[ ] b"]

    def test_position_1_inserts_at_top(self, todo_setup):
        TodoRunner().run("abc123", "a", None)
        TodoRunner().run("abc123", "1", "b")
        assert _goal_lines(todo_setup) == ["[ ] b", "[ ] a"]

    def test_position_0_updates_first_item_in_place(self, todo_setup):
        TodoRunner().run("abc123", "a", None)
        TodoRunner().run("abc123", "b", None)
        TodoRunner().run("abc123", "0", "replaced")
        assert _goal_lines(todo_setup) == ["[ ] replaced", "[ ] b"]

    def test_position_negative_one_updates_last_item_in_place(self, todo_setup):
        TodoRunner().run("abc123", "a", None)
        TodoRunner().run("abc123", "b", None)
        TodoRunner().run("abc123", "-1", "replaced")
        assert _goal_lines(todo_setup) == ["[ ] a", "[ ] replaced"]

    def test_position_0_preserves_done_state(self, todo_setup):
        TodoRunner().run("abc123", "a", None)
        TodoRunner().run_done("abc123", "1")
        TodoRunner().run("abc123", "0", "replaced")
        assert _goal_lines(todo_setup) == ["[x] replaced"]

    def test_position_0_on_empty_list_errors(self, todo_setup, capsys):
        with pytest.raises(SystemExit) as exc:
            TodoRunner().run("abc123", "0", "x")
        assert exc.value.code == 2
        assert "no goal at that position" in capsys.readouterr().out

    def test_position_below_negative_one_errors(self, todo_setup, capsys):
        with pytest.raises(SystemExit) as exc:
            TodoRunner().run("abc123", "-2", "x")
        assert exc.value.code == 2
        assert "position must be 0, -1, or >= 1" in capsys.readouterr().out

    def test_missing_text_exits_nonzero(self, todo_setup, capsys):
        with pytest.raises(SystemExit) as exc:
            TodoRunner().run("abc123", None, None)
        assert exc.value.code == 2
        assert "Usage: owrap todo" in capsys.readouterr().out

    def test_empty_target_falls_back_to_attached_session(
        self, todo_setup, monkeypatch,
    ):
        monkeypatch.setenv("SESSION_ID", "abc123")
        TodoRunner().run("", "an item", None)
        assert "an item" in todo_setup.joinpath("main.md").read_text()

    def test_empty_target_no_session_exits_nonzero(self, todo_setup, capsys):
        with pytest.raises(SystemExit) as exc:
            TodoRunner().run("", "an item", None)
        assert exc.value.code == 2
        assert "no target given" in capsys.readouterr().out

    def test_unrelated_sections_preserved(self, todo_setup):
        TodoRunner().run("abc123", "an item", None)
        text = todo_setup.joinpath("main.md").read_text()
        assert "## Overview\n\nKeep this.\n" in text
        assert "## Notes\n\nKeep this too.\n" in text


class TestTodoRunnerTargetResolution:
    def test_no_target_kind_errors(self, tmp_path, monkeypatch, capsys):
        _session(tmp_path, monkeypatch, workspace="test")
        with pytest.raises(SystemExit) as exc:
            TodoRunner().run("abc123", "text", None)
        assert exc.value.code == 2
        assert "no project/repository target configured" in capsys.readouterr().out

    def test_repository_only_session_errors(self, tmp_path, monkeypatch, capsys):
        root = tmp_path / "research"
        repo = root / "repositories" / "myrepo"
        repo.mkdir(parents=True)
        (repo / "myrepo.yaml").write_text(
            "schema_version: 1\nkind: repository\nid: myrepo\n"
            "main: memory.md\ncheckout: /tmp/myrepo\n",
        )
        (repo / "memory.md").write_text("# Architecture\n\nFacts.\n")
        monkeypatch.setattr(
            "owrap.utils.memory.records.get_workspace_config",
            lambda workspace: {"docs_root": str(root)},
        )
        _session(
            tmp_path, monkeypatch,
            target_kind="repository", repository_id="myrepo", workspace="test",
        )
        with pytest.raises(SystemExit) as exc:
            TodoRunner().run("abc123", "text", None)
        assert exc.value.code == 2
        assert "repository-only sessions have no project goals" in (
            capsys.readouterr().out
        )


class TestTodoClear:
    def test_clear_removes_done_items(self, todo_setup):
        TodoRunner().run("abc123", "a", None)
        TodoRunner().run("abc123", "b", None)
        TodoRunner().run_done("abc123", "1")
        TodoRunner().run_clear("abc123")
        assert _goal_lines(todo_setup) == ["[ ] b"]

    def test_clear_prints_count_removed(self, todo_setup, capsys):
        TodoRunner().run("abc123", "a", None)
        TodoRunner().run("abc123", "b", None)
        TodoRunner().run_done("abc123", "1")
        TodoRunner().run_done("abc123", "2")
        TodoRunner().run_clear("abc123")
        assert "cleared 2 done item" in capsys.readouterr().out


class TestTodoDone:
    def test_done_by_position(self, todo_setup):
        TodoRunner().run("abc123", "a", None)
        TodoRunner().run("abc123", "b", None)
        TodoRunner().run_done("abc123", "2")
        assert _goal_lines(todo_setup) == ["[ ] a", "[x] b"]

    def test_done_next_is_first_pending(self, todo_setup):
        TodoRunner().run("abc123", "a", None)
        TodoRunner().run("abc123", "b", None)
        TodoRunner().run("abc123", "c", None)
        TodoRunner().run_done("abc123", "1")
        TodoRunner().run_done("abc123", "next")
        assert _goal_lines(todo_setup) == ["[x] a", "[x] b", "[ ] c"]

    def test_done_next_no_pending_errors(self, todo_setup, capsys):
        TodoRunner().run("abc123", "a", None)
        TodoRunner().run_done("abc123", "1")
        with pytest.raises(SystemExit) as exc:
            TodoRunner().run_done("abc123", "next")
        assert exc.value.code == 2
        assert "goal selector must match one goal" in capsys.readouterr().out

    def test_done_by_unique_phrase(self, todo_setup):
        TodoRunner().run("abc123", "fix the widget", None)
        TodoRunner().run("abc123", "write docs", None)
        TodoRunner().run_done("abc123", "widget")
        assert _goal_lines(todo_setup) == [
            "[x] fix the widget", "[ ] write docs",
        ]

    def test_done_by_ambiguous_phrase_errors(self, todo_setup, capsys):
        TodoRunner().run("abc123", "fix the widget", None)
        TodoRunner().run("abc123", "fix the gadget", None)
        with pytest.raises(SystemExit) as exc:
            TodoRunner().run_done("abc123", "fix the")
        assert exc.value.code == 2
        assert "goal selector must match one goal" in capsys.readouterr().out

    def test_done_position_out_of_range_errors(self, todo_setup, capsys):
        TodoRunner().run("abc123", "a", None)
        with pytest.raises(SystemExit) as exc:
            TodoRunner().run_done("abc123", "5")
        assert exc.value.code == 2
        assert "goal selector must match one goal" in capsys.readouterr().out

    def test_done_missing_selector_errors(self, todo_setup, capsys):
        with pytest.raises(SystemExit) as exc:
            TodoRunner().run_done("abc123", None)
        assert exc.value.code == 2
        assert "Usage: owrap todo done" in capsys.readouterr().out


class TestTodoUpdate:
    def test_replaces_item_at_position_in_place(self, todo_setup):
        TodoRunner().run("abc123", "a", None)
        TodoRunner().run("abc123", "b", None)
        TodoRunner().run("abc123", "c", None)
        TodoRunner().run_update("abc123", "2", "replaced")
        assert _goal_lines(todo_setup) == ["[ ] a", "[ ] replaced", "[ ] c"]

    def test_position_0_updates_first_item(self, todo_setup):
        TodoRunner().run("abc123", "a", None)
        TodoRunner().run("abc123", "b", None)
        TodoRunner().run_update("abc123", "0", "replaced")
        assert _goal_lines(todo_setup) == ["[ ] replaced", "[ ] b"]

    def test_position_negative_one_updates_last_item(self, todo_setup):
        TodoRunner().run("abc123", "a", None)
        TodoRunner().run("abc123", "b", None)
        TodoRunner().run_update("abc123", "-1", "replaced")
        assert _goal_lines(todo_setup) == ["[ ] a", "[ ] replaced"]

    def test_preserves_done_state(self, todo_setup):
        TodoRunner().run("abc123", "a", None)
        TodoRunner().run("abc123", "b", None)
        TodoRunner().run_done("abc123", "2")
        TodoRunner().run_update("abc123", "2", "replaced")
        assert _goal_lines(todo_setup) == ["[ ] a", "[x] replaced"]

    def test_position_out_of_range_errors(self, todo_setup, capsys):
        TodoRunner().run("abc123", "a", None)
        with pytest.raises(SystemExit) as exc:
            TodoRunner().run_update("abc123", "5", "replaced")
        assert exc.value.code == 2
        assert "position out of range" in capsys.readouterr().out

    def test_non_integer_position_errors(self, todo_setup, capsys):
        TodoRunner().run("abc123", "a", None)
        with pytest.raises(SystemExit) as exc:
            TodoRunner().run_update("abc123", "two", "replaced")
        assert exc.value.code == 2
        assert "position must be an integer" in capsys.readouterr().out

    def test_position_below_negative_one_errors(self, todo_setup, capsys):
        TodoRunner().run("abc123", "a", None)
        with pytest.raises(SystemExit) as exc:
            TodoRunner().run_update("abc123", "-2", "replaced")
        assert exc.value.code == 2
        assert "position must be 0, -1, or >= 1" in capsys.readouterr().out

    def test_missing_text_exits_nonzero(self, todo_setup, capsys):
        TodoRunner().run("abc123", "a", None)
        with pytest.raises(SystemExit) as exc:
            TodoRunner().run_update("abc123", "1", None)
        assert exc.value.code == 2
        assert "Usage: owrap todo update" in capsys.readouterr().out

    def test_empty_list_errors(self, todo_setup, capsys):
        with pytest.raises(SystemExit) as exc:
            TodoRunner().run_update("abc123", "1", "replaced")
        assert exc.value.code == 2
        assert "no goal at that position" in capsys.readouterr().out


def _goal_lines(project):
    """
    Return each Goals-section item line (stripped of the leading '- ')
    from the project's main.md, in file order.
    """
    text = project.joinpath("main.md").read_text()
    body = text.split("## Goals\n\n", 1)[1].split("\n\n## Notes", 1)[0]
    return [line[2:] for line in body.splitlines() if line.startswith("- ")]
