from owrap.utils.parser.sections import (
    extract_section, replace_section, split_top_sections, merge_log_entries,
)


def test_extract_section_basic():
    text = "## Focus\nold focus\n\n## Key Locations\n- a\n- b\n\n## Decisions\n- c\n"
    assert extract_section(text, "## Focus") == "## Focus\nold focus"
    assert extract_section(text, "## Key Locations") == "## Key Locations\n- a\n- b"
    assert extract_section(text, "## Decisions") == "## Decisions\n- c"


def test_extract_section_not_found():
    assert extract_section("## Focus\nx\n", "## Missing") == ""


def test_extract_section_respects_heading_level():
    text = "## area\n### Components\n- a\n### Status\n- b\n"
    assert extract_section(text, "### Components") == "### Components\n- a"
    # The top-level "## area" section includes both subsections
    assert "### Status" in extract_section(text, "## area")


def test_replace_section_existing():
    text = "## Focus\nold\n\n## Key Locations\n- a\n"
    result = replace_section(text, "## Focus", "## Focus\nnew focus")
    assert "new focus" in result
    assert "old" not in result
    assert "## Key Locations\n- a" in result


def test_replace_section_appends_when_missing():
    text = "## Focus\nold\n"
    result = replace_section(text, "## Decisions", "## Decisions\n- new")
    assert "## Focus\nold" in result
    assert "## Decisions\n- new" in result


def test_replace_section_preserves_untouched_sections():
    text = "## A\n1\n\n## B\n2\n\n## C\n3\n"
    result = replace_section(text, "## B", "## B\nchanged")
    assert "## A\n1" in result
    assert "## B\nchanged" in result
    assert "## C\n3" in result


def test_split_top_sections_basic():
    text = (
        "# Context\n## Focus\nhi\n\n"
        "# Memory\n## main\n### Components\n- x\n\n"
        "# Project\n## main\n### Status\ny\n"
    )
    sections = split_top_sections(text, ("Context", "Memory", "Project"))
    assert set(sections) == {"Context", "Memory", "Project"}
    assert "## Focus" in sections["Context"]
    assert "### Components" in sections["Memory"]
    assert "### Status" in sections["Project"]


def test_split_top_sections_omits_missing():
    text = "# Context\n## Focus\nhi\n"
    sections = split_top_sections(text, ("Context", "Memory", "Project"))
    assert set(sections) == {"Context"}


def test_split_top_sections_ignores_text_before_first_known_header():
    text = "stray preamble\n# Context\n## Focus\nhi\n"
    sections = split_top_sections(text, ("Context", "Memory", "Project"))
    assert set(sections) == {"Context"}
    assert "stray preamble" not in sections["Context"]


def test_merge_log_entries_appends_new_lines():
    text = "## Key Locations\n- a.py — role a\n"
    result = merge_log_entries(
        text, "## Key Locations", ["- b.py — role b"], cap=5,
    )
    assert "- a.py — role a" in result
    assert "- b.py — role b" in result
    # appended: existing stays first, new goes after
    assert result.index("a.py") < result.index("b.py")


def test_merge_log_entries_dedupes_by_key():
    text = "## Key Locations\n- a.py — old reason\n"
    result = merge_log_entries(
        text, "## Key Locations", ["- a.py — new reason"], cap=5,
        key_fn=lambda l: l.split(" — ")[0].strip("- `"),
    )
    # the existing entry for a.py wins — new entry was a duplicate by key
    assert "old reason" in result
    assert "new reason" not in result


def test_merge_log_entries_caps_by_dropping_oldest_when_appending():
    text = "## Decisions\n- one\n- two\n- three\n"
    result = merge_log_entries(
        text, "## Decisions", ["- four"], cap=3,
    )
    lines = [l for l in extract_section(result, "## Decisions").splitlines()[1:]]
    assert lines == ["- two", "- three", "- four"]


def test_merge_log_entries_caps_by_dropping_oldest_when_prepending():
    text = "## Decisions\n- three\n- two\n- one\n"
    result = merge_log_entries(
        text, "## Decisions", ["- four"], cap=3, prepend=True,
    )
    lines = [l for l in extract_section(result, "## Decisions").splitlines()[1:]]
    assert lines == ["- four", "- three", "- two"]


def test_merge_log_entries_no_cap_keeps_everything():
    text = "### Components\n- a\n- b\n"
    result = merge_log_entries(
        text, "### Components", ["- c", "- d"], cap=None,
    )
    lines = extract_section(result, "### Components").splitlines()[1:]
    assert lines == ["- a", "- b", "- c", "- d"]


def test_merge_log_entries_returns_unchanged_when_nothing_new():
    text = "## Decisions\n- only one\n"
    result = merge_log_entries(
        text, "## Decisions", ["- only one"], cap=7,
        key_fn=lambda l: l.strip(),
    )
    assert result == text


def test_merge_log_entries_creates_heading_when_missing():
    text = "## Focus\nhi\n"
    result = merge_log_entries(text, "## Decisions", ["- new"], cap=7)
    assert "## Decisions" in result
    assert "- new" in result


def test_merge_log_entries_keep_fn_prunes_existing_entry():
    text = "## Key Locations\n- a.py — role a\n- b.py — role b\n"
    result = merge_log_entries(
        text, "## Key Locations", [], cap=5,
        keep_fn=lambda l: "a.py" in l,
    )
    assert "a.py" in result
    assert "b.py" not in result


def test_merge_log_entries_keep_fn_prunes_even_with_no_new_lines():
    text = "## Key Locations\n- gone.py — stale\n"
    result = merge_log_entries(
        text, "## Key Locations", [], cap=5, keep_fn=lambda l: False,
    )
    lines = extract_section(result, "## Key Locations").splitlines()[1:]
    assert lines == []


def test_merge_log_entries_keep_fn_noop_when_nothing_to_prune():
    text = "## Key Locations\n- a.py — role a\n"
    result = merge_log_entries(
        text, "## Key Locations", [], cap=5, keep_fn=lambda l: True,
    )
    assert result == text
