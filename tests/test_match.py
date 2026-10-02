import pytest

from owrap.utils.match import require_unique_match


class TestRequireUniqueMatch:
    def test_returns_sole_match(self):
        assert require_unique_match(["a"], "thing", "a") == "a"

    def test_no_match_errors(self, capsys):
        with pytest.raises(SystemExit) as exc:
            require_unique_match([], "thing", "query")
        assert exc.value.code == 2
        assert "no thing matches 'query'" in capsys.readouterr().out

    def test_ambiguous_errors_with_formatted_listing(self, capsys):
        with pytest.raises(SystemExit) as exc:
            require_unique_match(
                ["a", "b"], "thing", "query", formatter=lambda x: f"<{x}>",
            )
        assert exc.value.code == 2
        out = capsys.readouterr().out
        assert "AMBIGUOUS: 'query' matches 2 things:" in out
        assert "<a>" in out
        assert "<b>" in out

    def test_default_formatter_is_str(self, capsys):
        with pytest.raises(SystemExit):
            require_unique_match([1, 2], "thing", "query")
        out = capsys.readouterr().out
        assert "  1" in out
        assert "  2" in out
