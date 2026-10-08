from argparse import Namespace

import pytest

from owrap.commands.link import link_project_repository, unlink_project_repository
from owrap.runner import _cmd_attach, _cmd_detach
from owrap.utils.memory.records import _record

from .test_kinds import kinds_scope  # noqa: F401


def test_link_project_repository_appends_once(kinds_scope):
    link_project_repository("extra", "spare", workspace="test")
    link_project_repository("extra", "spare", workspace="test")
    record = _record(
        kinds_scope / "projects" / "spare" / "spare.yaml", "project", "spare",
    )
    assert record["repositories"] == ["extra"]


def test_unlink_project_repository_removes(kinds_scope):
    link_project_repository("extra", "spare", workspace="test")
    unlink_project_repository("extra", "spare", workspace="test")
    record = _record(
        kinds_scope / "projects" / "spare" / "spare.yaml", "project", "spare",
    )
    assert record["repositories"] == []


def test_link_project_repository_missing_repo_raises(kinds_scope):
    with pytest.raises(FileNotFoundError):
        link_project_repository("ghost", "spare", workspace="test")


def test_cmd_attach_repo_links(kinds_scope, capsys):
    _cmd_attach(
        Namespace(target_session_id="repo", arg2="extra", arg3="demo"),
        None, None, False,
    )
    record = _record(
        kinds_scope / "projects" / "demo" / "demo.yaml", "project", "demo",
    )
    assert "extra" in record["repositories"]
    assert "ATTACHED repo=extra project=demo" in capsys.readouterr().out


def test_cmd_detach_repo_unlinks(kinds_scope, capsys):
    link_project_repository("extra", "spare", workspace="test")
    _cmd_detach(
        Namespace(target="repo", arg2="extra", arg3="spare"), None, None, False,
    )
    record = _record(
        kinds_scope / "projects" / "spare" / "spare.yaml", "project", "spare",
    )
    assert record["repositories"] == []
    assert "DETACHED repo=extra project=spare" in capsys.readouterr().out
