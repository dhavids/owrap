import pytest

from owrap.commands.todo_cmd import TodoRunner


@pytest.fixture
def todo_setup(tmp_path, monkeypatch):
    """
    Isolate session storage and research root; write one session file.
    """
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    research_root = tmp_path / "research_root"
    research_root.mkdir()

    monkeypatch.setattr("owrap.utils.session.session_resolver.SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(
        "owrap.utils.paths._resolve_research_root", lambda: str(research_root),
    )
    (sessions_dir / "abc123.session").write_text(
        "session_id=abc123\nresearch=r\narea=main\n",
    )
    monkeypatch.delenv("SESSION_ID", raising=False)
    return research_root


class TestTodoRunner:
    def test_prepend_creates_file_and_section(self, todo_setup, capsys):
        TodoRunner().run("abc123", "first item", None)
        fpath = todo_setup / "todo" / "r.md"
        assert fpath.read_text() == "## main\n\n1. [ ] first item\n"

    def test_no_position_appends_to_end(self, todo_setup):
        TodoRunner().run("abc123", "first item", None)
        TodoRunner().run("abc123", "second item", None)
        fpath = todo_setup / "todo" / "r.md"
        assert fpath.read_text() == (
            "## main\n\n1. [ ] first item\n2. [ ] second item\n"
        )

    def test_insert_at_position_renumbers(self, todo_setup):
        TodoRunner().run("abc123", "a", None)
        TodoRunner().run("abc123", "b", None)
        TodoRunner().run("abc123", "2", "c")
        fpath = todo_setup / "todo" / "r.md"
        assert fpath.read_text() == "## main\n\n1. [ ] a\n2. [ ] c\n3. [ ] b\n"

    def test_position_1_inserts_at_top(self, todo_setup):
        TodoRunner().run("abc123", "a", None)
        TodoRunner().run("abc123", "1", "b")
        fpath = todo_setup / "todo" / "r.md"
        assert fpath.read_text() == "## main\n\n1. [ ] b\n2. [ ] a\n"

    def test_position_0_updates_first_item_in_place(self, todo_setup):
        TodoRunner().run("abc123", "a", None)
        TodoRunner().run("abc123", "b", None)
        TodoRunner().run("abc123", "0", "replaced")
        fpath = todo_setup / "todo" / "r.md"
        assert fpath.read_text() == "## main\n\n1. [ ] replaced\n2. [ ] b\n"

    def test_position_negative_one_updates_last_item_in_place(self, todo_setup):
        TodoRunner().run("abc123", "a", None)
        TodoRunner().run("abc123", "b", None)
        TodoRunner().run("abc123", "-1", "replaced")
        fpath = todo_setup / "todo" / "r.md"
        assert fpath.read_text() == "## main\n\n1. [ ] a\n2. [ ] replaced\n"

    def test_position_0_preserves_done_state(self, todo_setup):
        TodoRunner().run("abc123", "a", None)
        TodoRunner().run_done("abc123", "1")
        TodoRunner().run("abc123", "0", "replaced")
        fpath = todo_setup / "todo" / "r.md"
        assert fpath.read_text() == "## main\n\n1. [x] replaced\n"

    def test_position_0_on_empty_list_errors(self, todo_setup, capsys):
        with pytest.raises(SystemExit) as exc:
            TodoRunner().run("abc123", "0", "x")
        assert exc.value.code == 2
        assert "no item at position" in capsys.readouterr().out

    def test_position_below_negative_one_errors(self, todo_setup, capsys):
        with pytest.raises(SystemExit) as exc:
            TodoRunner().run("abc123", "-2", "x")
        assert exc.value.code == 2
        assert "position must be 0, -1, or >= 1" in capsys.readouterr().out

    def test_sections_stay_isolated(self, todo_setup):
        (todo_setup.parent / "sessions" / "def456.session").write_text(
            "session_id=def456\nresearch=r\narea=other\n",
        )
        TodoRunner().run("abc123", "main item", None)
        TodoRunner().run("def456", "other item", None)
        fpath = todo_setup / "todo" / "r.md"
        content = fpath.read_text()
        assert "## main\n\n1. [ ] main item" in content
        assert "## other\n\n1. [ ] other item" in content

    def test_no_match_exits_nonzero(self, todo_setup, capsys):
        with pytest.raises(SystemExit) as exc:
            TodoRunner().run("nonexistent", "text", None)
        assert exc.value.code == 2
        assert "no session found" in capsys.readouterr().out

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
        fpath = todo_setup / "todo" / "r.md"
        assert "an item" in fpath.read_text()

    def test_empty_target_no_session_exits_nonzero(self, todo_setup, capsys):
        with pytest.raises(SystemExit) as exc:
            TodoRunner().run("", "an item", None)
        assert exc.value.code == 2
        assert "no target given" in capsys.readouterr().out


class TestTodoClear:
    def _write_raw(self, todo_setup, text):
        fpath = todo_setup / "todo" / "r.md"
        fpath.parent.mkdir(parents=True, exist_ok=True)
        fpath.write_text(text)
        return fpath

    def test_clear_removes_done_and_renumbers(self, todo_setup):
        self._write_raw(
            todo_setup,
            "## main\n\n1. [x] done one\n2. [ ] keep one\n3. [x] done two\n"
            "4. [ ] keep two\n",
        )
        TodoRunner().run_clear("abc123")
        fpath = todo_setup / "todo" / "r.md"
        assert fpath.read_text() == "## main\n\n1. [ ] keep one\n2. [ ] keep two\n"

    def test_clear_only_touches_target_area(self, todo_setup):
        (todo_setup.parent / "sessions" / "def456.session").write_text(
            "session_id=def456\nresearch=r\narea=other\n",
        )
        self._write_raw(
            todo_setup,
            "## main\n\n1. [x] done\n\n## other\n\n1. [x] also done\n",
        )
        TodoRunner().run_clear("abc123")
        content = (todo_setup / "todo" / "r.md").read_text()
        assert "## main\n\n" in content
        assert "done" not in content.split("## other")[0]
        assert "1. [x] also done" in content

    def test_lines_without_a_checkbox_are_not_items(self, todo_setup):
        """
        A checkbox is the only item-start marker now (needed to support
        multi-line item text) — a line without one is neither an item nor
        preserved, it's just skipped.
        """
        self._write_raw(todo_setup, "## main\n\n1. legacy item\n2. [x] done\n")
        TodoRunner().run_clear("abc123")
        fpath = todo_setup / "todo" / "r.md"
        assert fpath.read_text() == "## main\n"

    def test_clear_prints_count_removed(self, todo_setup, capsys):
        self._write_raw(
            todo_setup, "## main\n\n1. [x] a\n2. [x] b\n3. [ ] c\n",
        )
        TodoRunner().run_clear("abc123")
        assert "cleared 2 done item" in capsys.readouterr().out


class TestTodoDone:
    def _write_raw(self, todo_setup, text):
        fpath = todo_setup / "todo" / "r.md"
        fpath.parent.mkdir(parents=True, exist_ok=True)
        fpath.write_text(text)
        return fpath

    def test_done_by_position(self, todo_setup):
        self._write_raw(todo_setup, "## main\n\n1. [ ] a\n2. [ ] b\n")
        TodoRunner().run_done("abc123", "2")
        fpath = todo_setup / "todo" / "r.md"
        assert fpath.read_text() == "## main\n\n1. [ ] a\n2. [x] b\n"

    def test_done_next_is_first_pending(self, todo_setup):
        self._write_raw(
            todo_setup, "## main\n\n1. [x] a\n2. [ ] b\n3. [ ] c\n",
        )
        TodoRunner().run_done("abc123", "next")
        fpath = todo_setup / "todo" / "r.md"
        assert fpath.read_text() == "## main\n\n1. [x] a\n2. [x] b\n3. [ ] c\n"

    def test_done_next_no_pending_errors(self, todo_setup, capsys):
        self._write_raw(todo_setup, "## main\n\n1. [x] a\n")
        with pytest.raises(SystemExit) as exc:
            TodoRunner().run_done("abc123", "next")
        assert exc.value.code == 2
        assert "no pending items" in capsys.readouterr().out

    def test_done_by_unique_phrase(self, todo_setup):
        self._write_raw(
            todo_setup, "## main\n\n1. [ ] fix the widget\n2. [ ] write docs\n",
        )
        TodoRunner().run_done("abc123", "widget")
        fpath = todo_setup / "todo" / "r.md"
        assert fpath.read_text() == (
            "## main\n\n1. [x] fix the widget\n2. [ ] write docs\n"
        )

    def test_done_by_phrase_ignores_already_done_items(self, todo_setup):
        self._write_raw(
            todo_setup, "## main\n\n1. [x] fix the widget\n2. [ ] fix the gadget\n",
        )
        TodoRunner().run_done("abc123", "fix the")
        fpath = todo_setup / "todo" / "r.md"
        assert fpath.read_text() == (
            "## main\n\n1. [x] fix the widget\n2. [x] fix the gadget\n"
        )

    def test_done_by_ambiguous_phrase_errors(self, todo_setup, capsys):
        self._write_raw(
            todo_setup, "## main\n\n1. [ ] fix the widget\n2. [ ] fix the gadget\n",
        )
        with pytest.raises(SystemExit) as exc:
            TodoRunner().run_done("abc123", "fix the")
        assert exc.value.code == 2
        assert "AMBIGUOUS" in capsys.readouterr().out

    def test_done_position_out_of_range_errors(self, todo_setup, capsys):
        self._write_raw(todo_setup, "## main\n\n1. [ ] a\n")
        with pytest.raises(SystemExit) as exc:
            TodoRunner().run_done("abc123", "5")
        assert exc.value.code == 2
        assert "out of range" in capsys.readouterr().out

    def test_done_missing_selector_errors(self, todo_setup, capsys):
        with pytest.raises(SystemExit) as exc:
            TodoRunner().run_done("abc123", None)
        assert exc.value.code == 2
        assert "Usage: owrap todo done" in capsys.readouterr().out


class TestTodoMultiLine:
    def _write_raw(self, todo_setup, text):
        fpath = todo_setup / "todo" / "r.md"
        fpath.parent.mkdir(parents=True, exist_ok=True)
        fpath.write_text(text)
        return fpath

    def test_done_preserves_other_items_wrapped_text(self, todo_setup):
        """
        An item's text can span multiple lines (anything up to the next
        checkbox line belongs to it) — marking a different item done must
        not truncate that wrapped text down to its first line.
        """
        self._write_raw(
            todo_setup,
            "## main\n\n"
            "1. [ ] short item\n"
            "2. [ ] first line of a long item\n"
            "   second line of the same item\n"
            "   third line of the same item\n",
        )
        TodoRunner().run_done("abc123", "1")
        fpath = todo_setup / "todo" / "r.md"
        assert fpath.read_text() == (
            "## main\n\n"
            "1. [x] short item\n"
            "2. [ ] first line of a long item\n"
            "   second line of the same item\n"
            "   third line of the same item\n"
        )

    def test_preamble_above_first_heading_is_preserved(self, todo_setup):
        self._write_raw(
            todo_setup,
            "# r — Todo\n\nSome intro text about this file.\n\n"
            "## main\n\n1. [ ] a\n",
        )
        TodoRunner().run_done("abc123", "1")
        fpath = todo_setup / "todo" / "r.md"
        assert fpath.read_text() == (
            "# r — Todo\n\nSome intro text about this file.\n\n"
            "## main\n\n1. [x] a\n"
        )
