"""
cli.py's own routing logic -- kind-alias resolution and the bare-kind
`do`-default dispatch -- isolated from any real kind via a toy
registry, since what's being verified is the routing itself, not any
concrete kind's behavior.
"""
import pytest

import owrap.cli as cli_module
from owrap.actions import Actions
from owrap.cli import main
from owrap.kind.dispatch import Dispatch


class _ToyDaemon(Actions):
    kind = "daemon"
    ensure_daemon_calls = 0

    @staticmethod
    def ensure_daemon():
        _ToyDaemon.ensure_daemon_calls += 1


class _ToyDispatch(Dispatch):
    kind = "read"
    messages = {"start": "read {file_path}"}

    def start(self, file_path=None, grep: str = None) -> None:
        self._ok("start", file_path=file_path)


class _ToyWithDo(Actions):
    kind = "sync"
    messages = {"do": "did the one thing"}

    def do(self):
        self._ok("do")


class _ToyWithoutDo(Actions):
    kind = "model"
    usage = {"set": {"usage": "<slot> <query>", "args": [], "examples": []}}
    messages = {"set": "set {slot}={query}"}

    def set(self, slot=None, query=None):
        if query is None:
            self._usage("set")
        self._ok("set", slot=slot, query=query)


class _ToySelf:
    BARE_ACTIONS = ()


@pytest.fixture(autouse=True)
def toy_registry(monkeypatch):
    _ToyDaemon.ensure_daemon_calls = 0
    registry = {
        "daemon": _ToyDaemon, "sync": _ToyWithDo, "model": _ToyWithoutDo,
        "read": _ToyDispatch, "self": _ToySelf,
    }
    monkeypatch.setattr(cli_module, "KIND_REGISTRY", registry)
    monkeypatch.setattr(cli_module, "KIND_ALIASES", {"m": "model"})
    return registry


def test_no_argv_at_all_prints_usage_and_exits_2(capsys):
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2
    assert "Usage: owrap <kind> <action>" in capsys.readouterr().out


def test_unknown_kind_fails_cleanly(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["nope"])
    assert exc.value.code == 2
    assert "no such kind 'nope'" in capsys.readouterr().out


def test_bare_kind_with_do_dispatches_to_do_not_help(capsys, toy_registry):
    main(["sync"])
    assert "did the one thing" in capsys.readouterr().out
    assert toy_registry["daemon"].ensure_daemon_calls == 1


def test_bare_kind_without_do_falls_back_to_help(capsys, toy_registry):
    with pytest.raises(SystemExit) as exc:
        main(["model"])
    assert exc.value.code == 2
    assert "Usage: owrap model set" in capsys.readouterr().out


def test_kind_alias_resolves_before_registry_lookup(capsys, toy_registry):
    """
    `owrap m set ...` must behave exactly like `owrap model set ...`.
    """
    main(["m", "set", "runner", "haiku"])
    assert "set runner=haiku" in capsys.readouterr().out


def test_daemon_itself_skips_its_own_ensure_daemon_call(capsys, toy_registry):
    """
    main()'s watchdog tick is skipped for the daemon kind itself --
    otherwise `owrap daemon <anything>` would recurse through its own
    liveness check before doing its actual job.
    """
    with pytest.raises(SystemExit) as exc:
        main(["daemon", "nonexistent_action"])
    assert exc.value.code == 2
    assert "does not support nonexistent_action" in capsys.readouterr().out
    assert toy_registry["daemon"].ensure_daemon_calls == 0


def test_explicit_action_with_args_bypasses_do_entirely(capsys, toy_registry):
    """
    Once an action word is given, it's used as-is even if the kind
    also defines `do` -- `do` only kicks in for the truly bare case.
    """
    with pytest.raises(SystemExit) as exc:
        main(["sync", "nonexistent_action"])
    assert exc.value.code == 2
    assert "does not support nonexistent_action" in capsys.readouterr().out


# Global shim flags (-a/--allow-all, --shell-pid) stripped before dispatch

def test_shell_pid_flag_and_value_stripped_before_dispatch(capsys, toy_registry):
    main(["model", "set", "--shell-pid", "1234", "a", "b"])
    assert capsys.readouterr().out.strip() == "set a=b"


def test_allow_all_flag_stripped_before_dispatch(capsys, toy_registry):
    main(["-a", "model", "set", "a", "b"])
    assert capsys.readouterr().out.strip() == "set a=b"


def test_allow_all_long_form_stripped_anywhere_in_argv(capsys, toy_registry):
    main(["model", "set", "a", "--allow-all", "b"])
    assert capsys.readouterr().out.strip() == "set a=b"


# A Dispatch kind's unrecognized action word is start's own first argument.

def test_dispatch_kind_bare_argument_defaults_to_start(capsys, toy_registry):
    main(["read", "file.py"])
    assert capsys.readouterr().out.strip() == "read file.py"


def test_dispatch_kind_flag_only_call_defaults_to_start(capsys, toy_registry):
    main(["read", "--grep", "pattern"])
    out = capsys.readouterr().out
    assert "read" in out  # start ran; grep was split out, not treated as the file


def test_dispatch_kind_recognized_action_is_not_reinterpreted(capsys, toy_registry):
    main(["read", "start", "file.py"])
    assert capsys.readouterr().out.strip() == "read file.py"


def test_non_dispatch_kind_unrecognized_action_still_errors(capsys, toy_registry):
    with pytest.raises(SystemExit) as exc:
        main(["sync", "bogus"])
    assert exc.value.code == 2
    assert "does not support bogus" in capsys.readouterr().out
