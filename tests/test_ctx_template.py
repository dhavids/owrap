"""
`Ctx.template` -- `owrap/ctx/manual.py`'s `template(subproject)` has
always existed (the planner's self-service fallback instructions when
opencode is down, listed by name in `CLAUDE.md`'s own Planner Working
Manual), but was never exposed as a real `Ctx` action, so the
documented command had been dead the whole time.

`Ctx.get` now also reaches it (and the PreCompact hook entry point)
as facets -- `owrap ctx get template`/`owrap ctx get hook` -- while a
bare `owrap ctx get` still reaches `_default_get` instead, since
`dispatch()` only calls `get` itself when there's at least one arg.
"""
from unittest.mock import patch

from owrap.kind.run.ctx import Ctx


def test_template_forwards_to_manual_template():
    with patch("owrap.kind.run.ctx.manual") as mock_manual:
        Ctx().template("docs")
    mock_manual.template.assert_called_once_with("docs")


def test_template_defaults_subproject_to_none():
    with patch("owrap.kind.run.ctx.manual") as mock_manual:
        Ctx().template()
    mock_manual.template.assert_called_once_with(None)


def test_get_template_facet_forwards_to_template():
    with patch("owrap.kind.run.ctx.manual") as mock_manual:
        Ctx().get("template", "docs")
    mock_manual.template.assert_called_once_with("docs")


def test_get_hook_facet_runs_hook_and_never_raises():
    with patch("owrap.kind.run.ctx.hook_run", side_effect=RuntimeError("boom")):
        Ctx().get("hook")  # must not raise


def test_get_hook_facet_always_prints_json_even_on_failure(capsys):
    with patch("owrap.kind.run.ctx.hook_run", side_effect=RuntimeError("boom")):
        Ctx().get("hook")
    assert capsys.readouterr().out.strip() == "{}"


def test_get_with_unknown_facet_shows_usage():
    with patch.object(Ctx, "_usage") as mock_usage:
        Ctx().get("bogus")
    mock_usage.assert_called_once_with("get")
