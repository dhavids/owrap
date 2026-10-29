import inspect
import os
import sys

from ..utils.memory.records import normalize_identity_kind, resolve_memory_target
from ..utils.session.resolver import session_file, _parse, resolve_session_or_exit

SHORT_FLAGS = {
    "-g": "grep", "-s": "summarise", "-d": "details", "-v": "verbose",
    "-p": "prompt_style", "-i": "id", "-m": "model", "-t": "timeout",
}


def usage_prefix(kind: str, action: str) -> str:
    """
    Build the `owrap <action> <kind>` command prefix for one action.
    """
    return f"owrap {action} {kind}".strip()


def dispatch(registry: dict, kind: str, action: str, *args) -> str:
    """
    Normalize `kind`, look it up in `registry`, and call its `action`
    method with `args`.

    `--flag`/`--flag value` tokens are pulled out first and passed as
    keywords (see `_split_flags`). The remaining positionals are padded
    with each missing parameter's default (or `None`), except for a
    method taking `*args`. With no args at all, the kind's
    `_default_<action>` runs if it defines one. Raises ValueError if
    `kind` isn't registered; the kind's own `action` method raises if it
    doesn't support it.
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
    Return the public callables `cls` contributes beyond `parent`,
    discovered from the class hierarchy.
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


def _split_flags(params, args: tuple) -> tuple:
    """
    Pull `--flag`/`--flag value` tokens out of `args`, matched by name
    (dashes to underscores) against the method's `params`: a bare switch
    if the parameter's default is `False`, a value flag otherwise.
    `SHORT_FLAGS` aliases single-dash forms for methods that have the
    named parameter. Unmatched tokens stay positional.
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
    own_only_writes = False

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
        A kind's default action, run for `owrap <kind>` with no action
        word. Refuses unless the kind overrides it.
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
        examples, without exiting.
        """
        prefix = usage_prefix(self.kind, action)
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
        Call `func`, turning an expected error into a clean failure exit,
        and return its result.
        """
        try:
            return func(*args, **kwargs)
        except (ValueError, FileNotFoundError, FileExistsError, OSError) as exc:
            self._fail(exc)

    def _resolve_target(self, target, noun=None, write=False):
        """
        Resolve a project/subproject name (`project`, `sub`, or
        `project/sub`), a session id, or a repository name -- or the
        currently attached session, if target is empty -- to its
        MemoryTarget. A kind with `own_only_writes` refuses a `write`
        to any record but the attached session's own.
        """
        noun = self.noun if noun is None else noun
        memory_target = self._named_memory_target(target) if target else None
        if memory_target is None:
            if target:
                sid = resolve_session_or_exit(target)
            else:
                sid = os.environ.get("SESSION_ID", "").strip()
                if not sid:
                    self._fail(self.target_messages["no_target"])
            session = _parse(session_file(sid))
            if not session.get("target_kind"):
                self._fail(
                    self.target_messages["no_target_kind"].format(sid=sid)
                )
            memory_target = self._edit(resolve_memory_target, session)
        if memory_target.kind == "repository":
            self._fail(self.target_messages["repository_only"].format(noun=noun))
        if write and self.own_only_writes and target:
            self._require_own(memory_target)
        return memory_target

    def _named_memory_target(self, token):
        """
        The record a project/subproject name resolves to, or None if
        `token` names no project (it may be a session id or repository).
        An ambiguous name fails with the qualified forms to use.
        """
        from ..utils.memory.names import find_target
        from ..kind.record.identity import current_workspace

        workspace = current_workspace()
        try:
            project_id, subproject_id = find_target(workspace, token)
        except ValueError as exc:
            if "ambiguous" in str(exc):
                self._fail(exc)
            return None
        return self._edit(resolve_memory_target, {
            "target_kind": "project", "project_id": project_id,
            "subproject_id": subproject_id, "workspace": workspace,
        })

    def _require_own(self, memory_target):
        """
        Fail unless `memory_target` is the attached session's own record.
        """
        sid = os.environ.get("SESSION_ID", "").strip()
        own = None
        if sid and session_file(sid).exists():
            session = _parse(session_file(sid))
            if session.get("target_kind"):
                own = self._edit(resolve_memory_target, session)
        if own is None or own.project_path != memory_target.project_path:
            self._fail(
                f"{self.noun} can be read from any project but written only "
                "to your own; to request a change elsewhere, file a proposal "
                "(`owrap get proposal template`)."
            )


# Imported last -- each depends on `Actions` existing above.
from .access import Access
from .modify import Modify
