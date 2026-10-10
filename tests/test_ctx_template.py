"""
`Ctx.template` -- `owrap/ctx/manual.py`'s `template(subproject)` has
always existed (the planner's self-service fallback instructions when
opencode is down, listed by name in `CLAUDE.md`'s own Planner Working
Manual as `owrap ctx-template`), but was never exposed as a real
`Ctx` action, so the documented command had been dead the whole time.
"""
from unittest.mock import patch

import pytest

from owrap.kind.run.ctx import Ctx


def test_template_forwards_to_manual_template():
    with patch("owrap.kind.run.ctx.manual") as mock_manual:
        Ctx().template("docs")
    mock_manual.template.assert_called_once_with("docs")


def test_template_defaults_subproject_to_none():
    with patch("owrap.kind.run.ctx.manual") as mock_manual:
        Ctx().template()
    mock_manual.template.assert_called_once_with(None)
