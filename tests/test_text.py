from owrap.utils.parser.text import preview, extract_useful_lines


def test_preview_short_text_unchanged():
    assert preview("one two three") == "one two three"


def test_preview_cuts_long_text():
    text = " ".join(str(i) for i in range(20))
    result = preview(text, words=3)
    assert result == "0 1 2 ... 17 18 19"


def test_extract_useful_lines_short_text_unchanged():
    assert extract_useful_lines("ATTACHED session=9f5f96") == "ATTACHED session=9f5f96"


def test_extract_useful_lines_keeps_last_line_when_nothing_matches():
    text = "collecting...\n" + ("." * 300) + "\n312 passed in 29.56s"
    assert extract_useful_lines(text) == "312 passed in 29.56s"


def test_extract_useful_lines_surfaces_buried_error():
    lines = ["line " + str(i) for i in range(20)] + ["Exception: boom"] + ["done"]
    result = extract_useful_lines("\n".join(lines))
    assert "Exception: boom" in result
    assert "done" in result


def test_extract_useful_lines_blank_text_returns_empty():
    assert extract_useful_lines("   \n  \n") == ""


def test_extract_useful_lines_respects_max_chars():
    text = "Exception: " + ("x" * 200) + "\nfinal status line"
    result = extract_useful_lines(text, max_chars=40)
    assert len(result) <= 40
