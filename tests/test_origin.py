from owrap.ctx.origin import missing_tags, tag_entries
from owrap.ctx.records import bullet_key


def _tag(existing, new, origin):
    return tag_entries(new, existing, origin, bullet_key)


def test_tags_follow_branch_and_commit_changes():
    first = _tag([], ["- a — x", "- b — y"], ("feat", "111"))
    assert first == ["- a — x [feat@111]", "- b — y"]
    log = first
    log += _tag(log, ["- c — z"], ("feat", "222"))
    log += _tag(log, ["- d — z"], ("other", "333"))
    log += _tag(log, ["- e — z", "- f — z"], None)
    assert log[2:] == [
        "- c — z [@222]", "- d — z [other@333]", "- e — z [base]", "- f — z",
    ]


def test_restated_fact_keeps_one_entry_without_a_tag():
    log = _tag([], ["- a — x"], ("feat", "111"))
    assert _tag(log, ["- a — x [feat@999]"], ("feat", "999")) == ["- a — x"]


def test_missing_tags_flags_only_new_untagged_lines_that_need_one():
    text = (
        "## Architecture\n\n- old — a [feat@111]\n- mid — b\n"
        "- new — c\n- newer — d\n"
    )
    known = {"old", "mid"}
    feat = ("feat", "111")

    assert missing_tags(text, known, [feat], ["## Architecture"], bullet_key) == []
    assert missing_tags(
        text, known, [("feat", "222")], ["## Architecture"], bullet_key,
    ) == [("## Architecture", "- new — c", "[@222]")]
    assert missing_tags(
        text, known, [feat, ("feat", "222")], ["## Architecture"], bullet_key,
    ) == []
