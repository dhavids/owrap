"""
`_resolve_kind_first`'s action-first fallback -- the shim's grammar
(`owrap start myproject`, `owrap add todo proj text`) reordered onto
`cli.py`'s kind-first shape via `ACTION_REGISTRY` (derived from which
kinds actually override each verb, never a hand-maintained list).
Isolated via a toy registry, since what's being verified is the
reordering logic itself, not any concrete kind's behavior.
"""
import pytest

import owrap.cli as cli_module
from owrap.cli import _resolve_kind_first, main


class _ToySelf:
    pass


@pytest.fixture(autouse=True)
def toy_action_registry(monkeypatch):
    registry = {
        "todo": object(), "session": object(), "daemon": object(),
        "self": _ToySelf,
    }
    monkeypatch.setattr(cli_module, "KIND_REGISTRY", registry)
    monkeypatch.setattr(cli_module, "KIND_ALIASES", {})
    monkeypatch.setattr(
        cli_module, "ACTION_REGISTRY",
        {
            "add": ["todo", "session"],
            "start": ["session", "daemon"],
            "clean": ["daemon"],
        },
    )
    return registry


def test_kind_first_argv_passes_through_unchanged():
    assert _resolve_kind_first(["todo", "add", "proj", "text"]) == (
        ["todo", "add", "proj", "text"]
    )


def test_verb_then_kind_is_swapped_to_kind_first():
    assert _resolve_kind_first(["add", "todo", "proj", "text"]) == (
        ["todo", "add", "proj", "text"]
    )


def test_bare_verb_with_single_supporting_kind_falls_back_to_it():
    assert _resolve_kind_first(["clean"]) == ["daemon", "clean"]


def test_bare_verb_ambiguous_between_kinds_prefers_session():
    assert _resolve_kind_first(["start", "myproject"]) == (
        ["session", "start", "myproject"]
    )


def test_unknown_token_returns_none():
    assert _resolve_kind_first(["bogus"]) is None


def test_verb_not_in_action_registry_returns_none():
    assert _resolve_kind_first(["get", "config"]) is None


def test_verb_ambiguous_among_many_kinds_defaults_to_self(monkeypatch):
    # "config" names no owning kind -- falls back to self, like session.
    monkeypatch.setattr(
        cli_module, "ACTION_REGISTRY", {"get": ["todo", "daemon", "self"]},
    )
    assert _resolve_kind_first(["get", "config"]) == ["self", "get", "config"]


def test_verb_ambiguous_among_many_kinds_prefers_a_matching_kind_over_self(
    monkeypatch,
):
    monkeypatch.setattr(
        cli_module, "ACTION_REGISTRY", {"get": ["todo", "daemon", "self"]},
    )
    assert _resolve_kind_first(["get", "daemon"]) == ["daemon", "get"]


def test_main_reports_ambiguous_verb_with_no_session_candidate(monkeypatch, capsys):
    monkeypatch.setattr(
        cli_module, "ACTION_REGISTRY", {"add": ["todo", "daemon"]},
    )
    with pytest.raises(SystemExit) as exc:
        main(["add", "proj", "text"])
    assert exc.value.code == 2
    out = capsys.readouterr().out
    assert "ambiguous" in out
    assert "owrap add {todo|daemon}" in out
