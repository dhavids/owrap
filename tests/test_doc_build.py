"""
`templates/build.py` -- extracts every `owrap ...` example across the
Markdown templates and checks it resolves through the real kind/action
resolver, and regenerates `self/commands.md`'s full command reference
from each kind's own `usage` dict. Covers the two real bugs found
while building it: the command regex matching config-key names like
`owrap_runner_enabled` as if they were commands (needed a word-boundary
fix), and a kind whose action only exists as `_default_<action>` (no
args at all) being flagged as unsupported.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "templates"))
import build  # noqa: E402


def test_fixed_tokens_stops_at_placeholder():
    assert build.fixed_tokens("owrap task start --msg <text>") == ["task", "start"]


def test_fixed_tokens_stops_at_bracket():
    assert build.fixed_tokens("owrap ctx-template [subproject]") == ["ctx-template"]


def test_fixed_tokens_keeps_literal_words():
    assert build.fixed_tokens("owrap daemon kill") == ["daemon", "kill"]


def test_command_regex_does_not_match_config_key_names():
    text = "default: `owrap_runner_enabled: false` is the gate."
    assert build.COMMAND_RE.search(text) is None


def test_command_regex_matches_real_commands():
    match = build.COMMAND_RE.search("`owrap project start <id>`")
    assert match.group(1) == "owrap project start <id>"


def test_verify_command_accepts_real_action():
    assert build.verify_command(["project", "start"]) is None


def test_verify_command_rejects_dead_kind():
    error = build.verify_command(["killservers"])
    assert error is not None and "does not resolve" in error


def test_verify_command_rejects_dead_action_on_real_kind():
    error = build.verify_command(["subproject", "start"])
    assert error is not None and "does not support action" in error


def test_verify_command_accepts_default_only_action():
    # Daemon.get only exists as the zero-args `_default_get` hook.
    assert build.verify_command(["daemon", "get"]) is None


def test_verify_command_accepts_dispatch_bare_arg():
    # Read is Dispatch; an unrecognized word is start's own first argument.
    assert build.verify_command(["read", "some_file.py"]) is None


def test_generate_commands_reference_lists_every_kind_with_usage():
    from owrap.kind import KIND_REGISTRY

    text = build.generate_commands_reference()
    for kind, cls in KIND_REGISTRY.items():
        if getattr(cls, "usage", {}):
            assert f"### `owrap {kind}`" in text
