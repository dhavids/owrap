import sys
import time

from .actions import Actions, dispatch
from .kind import ACTION_REGISTRY, KIND_ALIASES, KIND_REGISTRY
from .kind.dispatch import Dispatch
from .utils.log import rtlog
from .utils.parser.text import oneline

GLOBAL_BOOL_FLAGS = ("-a", "--allow-all")
GLOBAL_VALUE_FLAGS = ("--shell-pid",)


def _strip_global_flags(argv):
    """
    Remove the shim's own global flags, wherever they appear, before
    kind/action parsing.
    """
    cleaned = []
    i = 0
    while i < len(argv):
        token = argv[i]
        if token in GLOBAL_BOOL_FLAGS:
            i += 1
        elif token in GLOBAL_VALUE_FLAGS:
            i += 2
        else:
            cleaned.append(token)
            i += 1
    return cleaned


def _resolve_kind_first(argv):
    """
    Reorder a shim-style, action-first invocation onto `cli.py`'s
    kind-first shape, or leave `argv` unchanged if it already starts
    with a kind. Returns `None` if `argv[0]` resolves to neither.
    """
    token = argv[0]
    if (KIND_ALIASES.get(token, token)) in KIND_REGISTRY:
        return argv
    kinds = ACTION_REGISTRY.get(token, [])
    if not kinds:
        # Verbs with no owning kind (e.g. get) fall back to Self.BARE_ACTIONS.
        if token in KIND_REGISTRY["self"].BARE_ACTIONS:
            return ["self", token] + argv[1:]
        return None
    if len(argv) > 1:
        next_kind = KIND_ALIASES.get(argv[1], argv[1])
        if next_kind in kinds:
            return [next_kind, token] + argv[2:]
    # Lifecycle verbs (start/stop/restart) default to session when ambiguous.
    if "session" in kinds:
        return ["session", token] + argv[1:]
    if len(kinds) == 1:
        return [kinds[0], token] + argv[1:]
    print(
        f"ERROR: '{token}' is ambiguous -- specify a kind: "
        f"owrap {{{'|'.join(kinds)}}} {token} ..."
    )
    sys.exit(2)


def main(argv=None):
    """
    Entry point for the kind-first CLI: `owrap <kind> <action>
    [args...]`, falling back to the shim's action-first shape via
    `_resolve_kind_first`. Logs every resolved invocation to rtlog as
    `cmd.start`/`cmd.end`.
    """
    raw_argv = sys.argv[1:] if argv is None else argv
    argv = _strip_global_flags(raw_argv)
    if not argv:
        print("Usage: owrap <kind> <action> [args...]")
        sys.exit(2)

    token = argv[0]
    argv = _resolve_kind_first(argv)
    if argv is None:
        print(f"ERROR: no such kind '{token}'")
        sys.exit(2)

    kind = KIND_ALIASES.get(argv[0], argv[0])
    cls = KIND_REGISTRY[kind]

    # Watchdog tick: revive a daemon that died non-gracefully.
    if kind != "daemon":
        KIND_REGISTRY["daemon"].ensure_daemon()

    instance = cls()
    if len(argv) < 2:
        # help() exits on its own; a kind with no do() never reaches dispatch.
        if type(instance).do is Actions.do:
            instance.help()
        action, args = "do", ()
    else:
        action, *args = argv[1:]
        if issubclass(cls, Dispatch) and getattr(instance, action, None) is None:
            # Unrecognized action on a Dispatch kind is start's own first argument.
            action, args = "start", [action] + args

    cmd = f"{kind} {action}"
    started = time.time()
    rtlog.log("cmd.start", cmd=cmd, argv=" ".join(raw_argv)[:300])
    try:
        message = dispatch(KIND_REGISTRY, kind, action, *args)
    except (OSError, ValueError, FileExistsError, FileNotFoundError) as exc:
        rtlog.log(
            "cmd.end", cmd=cmd, rc=2, dur_s=round(time.time() - started, 2),
            error=oneline(exc),
        )
        print(f"ERROR: {exc}")
        sys.exit(2)
    fields = {"result": oneline(message)} if message else {}
    rtlog.log(
        "cmd.end", cmd=cmd, rc=0, dur_s=round(time.time() - started, 2), **fields,
    )
    if message:
        print(message)


if __name__ == "__main__":
    main()
