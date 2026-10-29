"""
`actions.added`/`actions.supports` -- the two primitives that derive
`kind.ACTION_REGISTRY` from which kinds genuinely override a verb
(by overriding the public method directly, or the private
`_<verb>`/`_on_<verb>` hook its default delegates to). Exercised
against the real `Modify`/`Run` hierarchy and the built
`ACTION_REGISTRY`.
"""

from owrap.actions import Actions, added, supports
from owrap.actions.modify import Modify
from owrap.kind import ACTION_REGISTRY, MODIFY_VERBS, RUN_VERBS
from owrap.kind.run import Run
from owrap.kind.run.session import Session


def test_added_discovers_modify_verbs_with_no_hardcoded_list():
    assert MODIFY_VERBS == {
        "add", "remove", "update", "clear", "done", "restore", "set",
    }


def test_added_discovers_run_only_verbs_beyond_modify():
    assert RUN_VERBS == {
        "start", "stop", "restart", "attach", "detach", "refresh",
        "kill", "clean", "wait",
    }


def test_added_excludes_private_and_inherited_names():
    assert "_add" not in added(Modify, Actions)
    assert "do" not in added(Modify, Actions)
    assert "help" not in added(Modify, Actions)


def test_supports_false_for_a_verb_the_kind_never_touched():
    assert supports(Session, "kill", Run) is False


def test_supports_true_for_a_hook_override():
    """
    `Session._on_stop` overrides `Stop`'s refusing default -- the
    private-hook half of the check, not a direct method override.
    """
    assert supports(Session, "stop", Run) is True


def test_supports_true_for_a_direct_public_override():
    """
    `Session.start` overrides `Start.start` directly, bypassing the
    `_on_start` hook entirely.
    """
    assert supports(Session, "start", Run) is True


def test_supports_false_when_attribute_is_entirely_absent():
    """
    A `Dispatch`-shaped kind has no `Modify` verbs at all -- `getattr`
    must come back `None`, not fall through to a false positive.
    """
    from owrap.kind.dispatch.agent import Agent
    assert supports(Agent, "add", Modify) is False


def test_action_registry_resolves_the_session_daemon_lifecycle_collision():
    """
    Both `Session` and `Daemon` override `stop`/`restart` (one
    directly, one via `_on_stop`/`_on_restart`) -- real ambiguity
    `cli.py`'s session-preference tiebreak exists to resolve, not a
    registry bug.
    """
    assert {"session", "daemon"} <= set(ACTION_REGISTRY["stop"])
    assert {"session", "daemon"} <= set(ACTION_REGISTRY["restart"])


def test_action_registry_has_no_entry_for_an_unsupported_verb():
    assert ACTION_REGISTRY.get("kill") == ["daemon"]
