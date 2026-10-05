from unittest.mock import patch

from owrap.manager import Manager
from owrap.utils.session.donow import check_donow


def test_check_donow_accepts_existing_context(tmp_path):
    context_file = tmp_path / "context.md"
    context_file.write_text("## Focus\nstarted\n")
    with patch(
        "owrap.utils.session.donow.context_path",
        return_value=context_file,
    ):
        assert check_donow("test123") is None


def test_check_donow_requests_missing_context_recovery(tmp_path):
    with patch(
        "owrap.utils.session.donow.context_path",
        return_value=tmp_path / "missing.md",
    ):
        result = check_donow("test123")

    assert "#DO NOW" in result
    assert "Context file missing" in result
    assert "Context Recovery" in result


def test_active_plan_is_capped_to_five_lines(tmp_path):
    manager = Manager.__new__(Manager)
    context_file = tmp_path / "context.md"
    context_file.write_text(
        "## Active Plan\n"
        "1. [x] line one\n"
        "2. [x] line two\n"
        "3. [x] line three\n"
        "4. [ ] line four\n"
        "5. [ ] line five\n"
        "6. [ ] line six\n"
        "7. [ ] line seven\n\n"
        "## Decisions\nA decision\n"
    )

    manager._cap_context_sections(context_file)

    content = context_file.read_text()
    assert "6. [ ] line six" not in content
    assert "7. [ ] line seven" not in content


def test_empty_active_plan_stays_empty(tmp_path):
    manager = Manager.__new__(Manager)
    context_file = tmp_path / "context.md"
    context_file.write_text(
        "## Active Plan\n\n## Decisions\nsome decision\n",
    )

    manager._cap_context_sections(context_file)

    content = context_file.read_text()
    assert "## Active Plan" in content
    assert "## Decisions" in content


def test_short_active_plan_is_preserved(tmp_path):
    manager = Manager.__new__(Manager)
    context_file = tmp_path / "context.md"
    context_file.write_text(
        "## Active Plan\n"
        "1. [ ] step one\n"
        "2. [ ] step two\n"
        "3. [ ] step three\n\n"
        "## Decisions\ndecision\n"
    )

    manager._cap_context_sections(context_file)

    content = context_file.read_text()
    assert "step one" in content
    assert "step two" in content
    assert "step three" in content
