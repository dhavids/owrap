from pathlib import Path

from owrap.utils.snippet import extract_snippet


def test_active_plan_with_phase(tmp_path):
    f = tmp_path / "plan.md"
    f.write_text("## [ACTIVE] p1 — Name\n**Research:** x\n**Phase:** Do thing\n")
    assert extract_snippet(f) == "p1 — Do thing"


def test_active_plan_without_phase(tmp_path):
    f = tmp_path / "plan.md"
    f.write_text("## [ACTIVE] p1 — Name\n")
    assert extract_snippet(f) == "p1"


def test_do_section(tmp_path):
    f = tmp_path / "task.md"
    f.write_text("## Do\n\nFix the widget\n")
    assert extract_snippet(f) == "Fix the widget"


def test_first_line_hash_fallback(tmp_path):
    f = tmp_path / "plan.md"
    f.write_text("# Exec task: p067fcf-39 — kill orphaned duplicate keepalive daemon\n\nbody...")
    assert extract_snippet(f) == "Exec task: p067fcf-39 — kill orphaned duplicate keepalive daemon"


def test_nonexistent_path():
    p = Path("/nonexistent/snippet_test_file.md")
    assert extract_snippet(p, default="exec") == "exec"


def test_no_match_default(tmp_path):
    f = tmp_path / "plain.txt"
    f.write_text("just some text\nno headers here\n")
    assert extract_snippet(f, default="fallback") == "fallback"


def test_strips_context_header(tmp_path):
    f = tmp_path / "task.md"
    f.write_text("## Context\nFirst read exec.md, then read foo.md before starting this task.\n\n# Exec task: do the thing\n\nbody...")
    assert extract_snippet(f) == "Exec task: do the thing"


def test_strips_context_header_and_finds_do(tmp_path):
    f = tmp_path / "task.md"
    f.write_text("## Context\nFirst read foo.md before starting this task.\n\n## Do\n\nFix the widget\n")
    assert extract_snippet(f) == "Fix the widget"
