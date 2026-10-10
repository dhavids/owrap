import inspect
import os
import sys

from ..utils.memory.records import normalize_identity_kind, resolve_memory_target
from ..utils.session.resolver import session_file, _parse, resolve_session_or_exit


def dispatch(registry: dict, kind: str, action: str, *args) -> str:
    """
    Normalize `kind`, look it up in `registry`, and call its `action`
    method with `args` -- `--flag`/`--flag value` tokens are pulled
    out first and passed as keywords (see `_split_flags`), then
    whatever positionals remain are padded with each still-missing
    parameter's own default (or `None`, for one with no default) up
    to the method's own remaining parameter count, so a missing
    trailing argument reaches the method as its real default (for
    its own usage check) rather than raising a raw TypeError, without
    masking any default other than `None` -- skipped for a method
    taking `*args`, since those already tolerate fewer arguments via
    their own defaults. Raises ValueError if `kind` isn't registered;
    the kind's own `action` method raises if it doesn't support it.
    If called with no args at all and the kind defines
    `_default_<action>`, that runs instead -- a kind's own fallback
    for an ambiguous bare call.
    """
    kind = normalize_identity_kind(kind)
    cls = registry.get(kind)
    if cls is None:
        raise ValueError(f"no such kind '{kind}'")
    instance = cls()
    if not args:
        default = getattr(instance, f"_default_{action}", None)
        if default is not None:
            return default()
    method = getattr(instance, action, None)
    if method is None:
        raise ValueError(f"{kind} does not support {action}")
    params = inspect.signature(method).parameters
    args, kwargs = _split_flags(params, args)
    has_var_positional = any(
        p.kind is inspect.Parameter.VAR_POSITIONAL for p in params.values()
    )
    if not has_var_positional:
        # A flag may name a parameter that isn't the trailing one (e.g.
        # `--project` sits between `project_name` and `repository`) --
        # positional args can't skip over it by position alone, so every
        # remaining slot is bound by name instead of splicing *args.
        fillable = [
            name for name, p in params.items()
            if p.kind in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            )
            and name not in kwargs
        ]
        padded = args + tuple(
            None if params[name].default is inspect.Parameter.empty
            else params[name].default
            for name in fillable[len(args):]
        )
        kwargs.update(zip(fillable, padded))
        args = padded[len(fillable):]
    return method(*args, **kwargs)


def added(cls: type, parent: type) -> set:
    """
    Public callables `cls` contributes beyond `parent` -- the verbs
    a category layer (`Modify`, `Run`) adds, discovered from the
    class hierarchy instead of a hand-maintained name list, so a
    kind never has to declare which verbs it uses.
    """
    parent_names = set(dir(parent))
    return {
        name for name in dir(cls)
        if name not in parent_names and not name.startswith("_")
        and callable(getattr(cls, name))
    }


def supports(cls: type, action: str, base: type) -> bool:
    """
    True if `cls` overrides `action` itself, or the private hook
    (`_<action>`/`_on_<action>`) its default implementation
    delegates to -- the same check each mixin's own refusing stub
    already makes before raising "does not support". `base` is the
    class whose inherited default represents "not yet overridden".
    """
    cls_method = getattr(cls, action, None)
    if cls_method is None:
        return False
    if cls_method is not getattr(base, action, None):
        return True
    for hook in (f"_{action}", f"_on_{action}"):
        if (hasattr(base, hook)
                and getattr(cls, hook, None) is not getattr(base, hook, None)):
            return True
    return False


SHORT_FLAGS = {
    "-g": "grep", "-s": "summarise", "-d": "details", "-v": "verbose",
    "-p": "prompt_style", "-i": "id", "-m": "model", "-t": "timeout",
}


def _split_flags(params, args: tuple) -> tuple:
    """
    Pull `--flag`/`--flag value` tokens out of `args`, matched by
    name (dashes to underscores) against the resolved method's own
    `params` -- a bare switch if that parameter's default is
    `False`, a value flag otherwise. `SHORT_FLAGS` aliases a handful
    of single-dash forms (`-i`, `-t`, `-m`, ...) reused verbatim
    across several dispatch kinds; each only fires for a method that
    actually has the parameter it names, so it stays scoped per kind
    without a hand-maintained per-kind list. A token matching neither
    is left in place as a positional, so the method's own usage check
    reports it instead of silently dropping it.
    """
    positional, kwargs = [], {}
    args = list(args)
    i = 0
    while i < len(args):
        token = args[i]
        if isinstance(token, str) and token in SHORT_FLAGS:
            name = SHORT_FLAGS[token]
        elif isinstance(token, str) and token.startswith("--"):
            name = token[2:].replace("-", "_")
        else:
            name = None
        if name in params:
            if params[name].default is False:
                kwargs[name] = True
                i += 1
            else:
                i += 1
                kwargs[name] = args[i] if i < len(args) else None
                i += 1
        else:
            positional.append(token)
            i += 1
    return tuple(positional), kwargs


class Actions:
    """
    Base for a managed kind: declares no verbs of its own. `Modify`
    and `Run` each declare the verbs genuinely available to their
    category (as refusing-by-default stubs); a kind that doesn't
    belong to a category simply doesn't have that category's methods
    at all, so `dispatch` can tell "unsupported" apart from "not yet
    overridden" by attribute presence alone.
    """

    kind = ""
    usage = {}
    messages = {}
    noun = "data"

    target_messages = {
        "no_target": "no target given and no session attached.",
        "no_target_kind": "session {sid} has no project/repository target configured.",
        "repository_only": "repository-only sessions have no project {noun}",
    }

    def help(self):
        """
        Print the usage/examples block for every action this kind has
        registered in `usage`, then exit(2) -- the entry point
        `cli.py` calls when a kind is given with no action and no
        `do` of its own.
        """
        for i, action in enumerate(self.usage):
            if i:
                print()
            self._print_usage(action)
        sys.exit(2)

    def do(self, *args, **kwargs):
        """
        A kind's single default action, run when it's invoked with
        no action word at all (`owrap <kind>` alone dispatches here
        instead of to `help`). Refuses by default; a kind for which
        one verb genuinely is "the obvious thing to do" overrides
        this directly -- it's never implied by `start` or any other
        verb.
        """
        raise ValueError(f"{self.kind} does not support do")


    # Private Methods

    def _ok(self, action, **fields):
        """
        Print the success-message template registered for `action` in
        `messages`, formatted with `fields`.
        """
        print(self.messages[action].format(**fields))

    def _usage(self, action):
        """
        Print the usage/examples block registered for `action` in
        `usage` and exit(2).
        """
        self._print_usage(action)
        sys.exit(2)

    def _print_usage(self, action):
        """
        Print one action's usage line, argument descriptions, and
        examples, without exiting. A kind's `usage` entries hold only
        the argument shape and descriptions; the `owrap <kind>
        <action>` prefix is built here, not hardcoded per kind.
        """
        prefix = f"owrap {self.kind} {action}"
        spec = self.usage.get(action, {})
        print(f"Usage: {prefix} {spec.get('usage', '')}".rstrip())
        args = spec.get("args", [])
        if args:
            print()
            width = max(len(name) for name, _ in args)
            for name, description in args:
                print(f"  {name.ljust(width)}  {description}")
        examples = spec.get("examples", [])
        if examples:
            print()
            print("Examples:")
            for line in examples:
                print(f"  {prefix} {line}")

    def _fail(self, message):
        """
        Print `ERROR: message` and exit(2).
        """
        print(f"ERROR: {message}")
        sys.exit(2)

    def _edit(self, func, *args, **kwargs):
        """
        Call `func`, converting one of its expected errors into a
        clean failure exit instead of a raw traceback, and returning
        whatever `func` returns on success.
        """
        try:
            return func(*args, **kwargs)
        except (ValueError, FileNotFoundError, FileExistsError, OSError) as exc:
            self._fail(exc)

    def _resolve_target(self, target, noun=None):
        """
        Resolve a session id/project/repository name (or the currently
        attached session, if target is empty) to its project MemoryTarget.
        Available to any action that needs one -- most won't call it.
        """
        noun = self.noun if noun is None else noun
        if target:
            sid = resolve_session_or_exit(target)
        else:
            sid = os.environ.get("SESSION_ID", "").strip()
            if not sid:
                self._fail(self.target_messages["no_target"])

        session = _parse(session_file(sid))
        if not session.get("target_kind"):
            self._fail(self.target_messages["no_target_kind"].format(sid=sid))
        memory_target = self._edit(resolve_memory_target, session)
        if memory_target.kind == "repository":
            self._fail(self.target_messages["repository_only"].format(noun=noun))
        return memory_target


# Imported last -- each depends on `Actions` existing above.
from .access import Access
from .modify import Modify
