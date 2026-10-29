"""
`Ctx.template`, and the `template`/`hook` facets of `Ctx.get`.
"""
from unittest.mock import patch

from owrap.kind.dispatch.ctx import Ctx


def test_template_forwards_to_manual_template():
    with patch("owrap.kind.dispatch.ctx.manual") as mock_manual:
        Ctx().template("docs")
    mock_manual.template.assert_called_once_with("docs")


def test_template_defaults_subproject_to_none():
    with patch("owrap.kind.dispatch.ctx.manual") as mock_manual:
        Ctx().template()
    mock_manual.template.assert_called_once_with(None)


def test_get_template_facet_forwards_to_template():
    with patch("owrap.kind.dispatch.ctx.manual") as mock_manual:
        Ctx().get("template", "docs")
    mock_manual.template.assert_called_once_with("docs")


def test_get_hook_facet_runs_hook_and_never_raises():
    with patch("owrap.kind.dispatch.ctx.hook_run", side_effect=RuntimeError("boom")):
        # Must not raise
        Ctx().get("hook")


def test_get_hook_facet_always_prints_json_even_on_failure(capsys):
    with patch("owrap.kind.dispatch.ctx.hook_run", side_effect=RuntimeError("boom")):
        Ctx().get("hook")
    assert capsys.readouterr().out.strip() == "{}"


def test_get_with_unknown_facet_shows_usage():
    with patch.object(Ctx, "_usage") as mock_usage:
        Ctx().get("bogus")
    mock_usage.assert_called_once_with("get")
