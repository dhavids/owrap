"""
`Worktree` (kind/run/worktree.py) -- the branch-session verbs split
out of `Session`: real Git worktrees per repository, not the shared
checkout `Session.add` gives an ordinary child. `SessionWorkflow` is
mocked here since its own git mechanics are already covered by
`tests/test_session_workflow.py`; what's being verified is that
`Worktree` calls it with the right arguments and reports the right
thing, plus that `Session` no longer holds this logic.
"""
from unittest.mock import MagicMock, patch

import pytest

from owrap.kind.run.session import Session
from owrap.kind.run.worktree import Worktree


@pytest.fixture
def workflow():
    with patch("owrap.kind.run.worktree.SessionWorkflow") as mock_cls:
        yield mock_cls.return_value


def test_add_creates_a_branch_session_and_prints_worktrees(workflow, capsys):
    workflow.create.return_value = {
        "session_id": "abc123", "session_name": "feature-x",
        "branch_worktrees": (
            '{"repo1": {"path": "/x/repo1", "ref": "feature/x"}}'
        ),
    }
    Worktree().add("feature-x", "feature/x")
    workflow.create.assert_called_once_with("branch", "feature-x", "feature/x")
    out = capsys.readouterr().out
    assert "Branch session: abc123 (feature-x)" in out
    assert "repo1: /x/repo1 [feature/x]" in out
    assert "__OWRAP_EXPORT__ SESSION_ID=abc123" in out


def test_add_defaults_name_and_ref_to_empty(workflow):
    workflow.create.return_value = {
        "session_id": "x", "session_name": "branch-x", "branch_worktrees": "{}",
    }
    Worktree().add()
    workflow.create.assert_called_once_with("branch", "", "")


def test_add_fails_cleanly_on_a_workflow_error(workflow, capsys):
    workflow.create.side_effect = ValueError("repository has uncommitted changes")
    with pytest.raises(SystemExit) as exc:
        Worktree().add("feature-x")
    assert exc.value.code == 2
    assert "repository has uncommitted changes" in capsys.readouterr().out


def test_done_previews_by_default_and_applies_with_the_keyword(workflow, capsys):
    workflow.merge_branch.return_value = {
        "repositories": {
            "repo1": {"ref": "feature/x", "base_ref": "main", "commits": "", "stat": ""},
        },
        "applied": False,
    }
    Worktree().done("abc123", "repo1")
    workflow.merge_branch.assert_called_once_with("abc123", False, "repo1")
    assert "Preview only" in capsys.readouterr().out

    workflow.merge_branch.return_value["applied"] = True
    Worktree().done("abc123", "repo1", "apply")
    workflow.merge_branch.assert_called_with("abc123", True, "repo1")
    assert "Git merge applied." in capsys.readouterr().out


def test_done_defaults_sid_and_repo_to_empty_for_the_attached_session(workflow):
    workflow.merge_branch.return_value = {"repositories": {}, "applied": False}
    Worktree().done()
    workflow.merge_branch.assert_called_once_with("", False, "")


def test_clear_previews_by_default_and_applies_with_the_keyword(workflow, capsys):
    workflow.cleanup_branch.return_value = {
        "repositories": {"repo1": {"path": "/x/repo1"}}, "applied": False,
    }
    Worktree().clear("abc123")
    workflow.cleanup_branch.assert_called_once_with("abc123", False)
    assert "Preview only" in capsys.readouterr().out

    workflow.cleanup_branch.return_value["applied"] = True
    Worktree().clear("abc123", "apply")
    workflow.cleanup_branch.assert_called_with("abc123", True)
    assert "Worktrees removed." in capsys.readouterr().out


# Session dropped this logic entirely -- no second copy left behind

def test_session_no_longer_supports_clear():
    with pytest.raises(ValueError, match="does not support clear"):
        Session().clear()


def test_session_done_no_longer_understands_the_merge_keyword(monkeypatch, capsys):
    """
    `Session.done("merge", ...)` now just tries to collapse a child
    session literally named "merge" -- it no longer special-cases
    the keyword at all, since that behavior moved to `Worktree.done`.
    """
    collapse = MagicMock(side_effect=ValueError("no such child session: merge"))
    monkeypatch.setattr(
        "owrap.kind.run.session.SessionWorkflow",
        MagicMock(return_value=MagicMock(collapse=collapse)),
    )
    with pytest.raises(SystemExit) as exc:
        Session().done("merge")
    assert exc.value.code == 2
    collapse.assert_called_once_with("merge", False)
