import sys
import time

from .actions import Actions, dispatch
from .kind import ACTION_REGISTRY, KIND_ALIASES, KIND_REGISTRY
from .kind.dispatch import Dispatch
from .utils.log import rtlog
from .utils.parser.text import oneline

GLOBAL_BOOL_FLAGS = ("-a", "--allow-all")
GLOBAL_VALUE_FLAGS = ("--shell-pid",)
HELP_FLAGS = ("-h", "--help")
# High-frequency polling commands that would otherwise drown out rtlog.
UNLOGGED_CMDS = ("stat do", "permit do")


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
    Reorder an action-first invocation (`owrap <action> <kind>
    ...`) onto `dispatch()`'s internal kind-first shape, or leave
    `argv` unchanged if it already starts with a kind. Returns
    `None` if `argv[0]` resolves to neither.
    """
    token = argv[0]
    kinds = ACTION_REGISTRY.get(token, [])
    # A second token naming an owning kind settles token being both (e.g. update).
    if len(argv) > 1:
        next_kind = KIND_ALIASES.get(argv[1], argv[1])
        if next_kind in kinds:
            return [next_kind, token] + argv[2:]
    if (KIND_ALIASES.get(token, token)) in KIND_REGISTRY:
        return argv
    if not kinds:
        return None
    # Lifecycle verbs (start/stop/restart) default to session when ambiguous.
    if "session" in kinds:
        return ["session", token] + argv[1:]
    # Verbs ambiguous among many kinds default to Self (e.g. get's own facets).
    if "self" in kinds:
        return ["self", token] + argv[1:]
    if len(kinds) == 1:
        return [kinds[0], token] + argv[1:]
    print(
        f"ERROR: '{token}' is ambiguous -- specify a kind: "
        f"owrap {token} {{{'|'.join(kinds)}}} ..."
    )
    sys.exit(2)


def main(argv=None):
    """
    Entry point for the CLI: `owrap <action> <kind> [args...]` is
    the canonical form, with the older `owrap <kind> <action>
    [args...]` still accepted -- `_resolve_kind_first` normalizes
    either onto `dispatch()`'s internal kind-first shape. A bare
    `-h`/`--help` anywhere prints the resolved kind's (or action's)
    usage instead of dispatching. Logs every resolved invocation to
    rtlog as `cmd.start`/`cmd.end`, except `UNLOGGED_CMDS`.
    """
    raw_argv = sys.argv[1:] if argv is None else argv
    argv = _strip_global_flags(raw_argv)
    help_requested = any(token in HELP_FLAGS for token in argv)
    argv = [token for token in argv if token not in HELP_FLAGS]
    if not argv:
        print("Usage: owrap <action> <kind> [args...]")
        sys.exit(0 if help_requested else 2)

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
        if issubclass(cls, Dispatch) and not help_requested:
            # A Dispatch kind needs no explicit "start" -- a bare call is it.
            action, args = "start", ()
        # help() exits on its own; a kind with no do() never reaches dispatch.
        elif help_requested or type(instance).do is Actions.do:
            instance.help()
            action, args = "do", ()
        else:
            action, args = "do", ()
    else:
        action, *args = argv[1:]
        if issubclass(cls, Dispatch) and getattr(instance, action, None) is None:
            # Unrecognized action on a Dispatch kind is start's own first argument.
            action, args = "start", [action] + args
        if help_requested:
            instance._usage(action)

    cmd = f"{kind} {action}"
    log_this = cmd not in UNLOGGED_CMDS
    started = time.time()
    if log_this:
        rtlog.log("cmd.start", cmd=cmd, argv=" ".join(raw_argv)[:300])
    try:
        message = dispatch(KIND_REGISTRY, kind, action, *args)
    except (OSError, ValueError, FileExistsError, FileNotFoundError) as exc:
        if log_this:
            rtlog.log(
                "cmd.end", cmd=cmd, rc=2, dur_s=round(time.time() - started, 2),
                error=oneline(exc),
            )
        print(f"ERROR: {exc}")
        sys.exit(2)
    if log_this:
        fields = {"result": oneline(message)} if message else {}
        rtlog.log(
            "cmd.end", cmd=cmd, rc=0, dur_s=round(time.time() - started, 2), **fields,
        )
    if message:
        print(message)


if __name__ == "__main__":
    main()
