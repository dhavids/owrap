from owrap.utils.output_parser import OutputParser


class TestOutputParser:
    def test_strips_ansi_reset_and_gray(self):
        parser = OutputParser()
        result = parser.feed("\x1b[0m→ \x1b[0mRead file.md\r\n")
        result += parser.flush()
        assert "\x1b" not in result
        assert result == "→ Read file.md\n"

    def test_crlf_normalized_to_lf(self):
        parser = OutputParser()
        result = parser.feed("line1\r\nline2\r\n")
        result += parser.flush()
        assert result == "line1\nline2\n"

    def test_model_line_extracted(self):
        parser = OutputParser()
        result = parser.feed("> build \u00b7 deepseek-v4-pro\r\n")
        assert "model: deepseek-v4-pro" in result
        assert "> build" not in result
        assert parser.model == "deepseek-v4-pro"

    def test_model_line_newline_preserved_across_feeds(self):
        parser = OutputParser()
        r1 = parser.feed("> build \u00b7 deepseek-v4-pro\r\n")
        r2 = parser.feed("\x1b[0m\u2192 \x1b[0mRead /path/to/task.md\r\n")
        combined = r1 + r2 + parser.flush()
        assert "model: deepseek-v4-pro\n" in combined
        assert "model: deepseek-v4-pro\u2192" not in combined

    def test_split_ansi_escape_across_feeds(self):
        parser = OutputParser()
        r1 = parser.feed("\x1b[0")
        r2 = parser.feed("m→ Read x\r\n")
        r3 = parser.flush()
        combined = r1 + r2 + r3
        assert "\x1b" not in combined
        assert "[" not in combined or "[" not in combined.replace("→ Read x\n", "")
        assert combined == "→ Read x\n"

    def test_diff_block_passthrough(self):
        parser = OutputParser()
        chunk = (
            "\x1b[0mIndex: foo.py\r\n"
            "\x1b[0m--- a/foo.py\r\n"
            "\x1b[0m+++ b/foo.py\r\n"
            "\x1b[0m@@ -1,3 +1,4 @@\r\n"
            "\x1b[0m-line1\r\n"
            "\x1b[0m+line1a\r\n"
        )
        result = parser.feed(chunk)
        result += parser.flush()
        assert "Index: foo.py\n" in result
        assert "--- a/foo.py\n" in result
        assert "+++ b/foo.py\n" in result
        assert "@@ -1,3 +1,4 @@\n" in result
        assert "-line1\n" in result
        assert "+line1a\n" in result
        assert "\x1b" not in result

    def test_flush_returns_remaining_buffer(self):
        parser = OutputParser()
        r1 = parser.feed("\x1b[9")
        assert r1 == ""
        r2 = parser.flush()
        assert r2 == "\x1b[9"
