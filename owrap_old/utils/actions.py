import inspect

from owrap.utils.memory.records import normalize_identity_kind


class Actions:
    """
    Base for a managed kind: declares every dispatchable action, each
    refusing by default. A kind overrides only the ones it actually
    supports. add/remove/update/clear/done are the record-editing
    verbs; start/stop/restart/attach/detach/refresh are the
    live-session/process verbs a Entity kind uses instead (or
    alongside -- nothing stops a Record kind from also overriding
    attach/detach, as Repository does for repo-link).
    """

    kind = ""

    def add(self, *args):
        raise ValueError(f"{self.kind} does not support add")

    def remove(self, *args):
        raise ValueError(f"{self.kind} does not support remove")

    def update(self, *args):
        raise ValueError(f"{self.kind} does not support update")

    def clear(self, *args):
        raise ValueError(f"{self.kind} does not support clear")

    def done(self, *args):
        raise ValueError(f"{self.kind} does not support done")

    def start(self, *args):
        raise ValueError(f"{self.kind} does not support start")

    def stop(self, *args):
        raise ValueError(f"{self.kind} does not support stop")

    def restart(self, *args):
        raise ValueError(f"{self.kind} does not support restart")

    def attach(self, *args):
        raise ValueError(f"{self.kind} does not support attach")

    def detach(self, *args):
        raise ValueError(f"{self.kind} does not support detach")

    def refresh(self, *args):
        raise ValueError(f"{self.kind} does not support refresh")


class Record(Actions):
    """
    A kind that owns its own directory and `<id>.yaml` under docs_root
    (today: project, repository).
    """


class NestedRecord(Actions):
    """
    A kind stored as an entry inside a parent Record's yaml, with its
    own markdown file in the parent's directory but no directory of
    its own (today: subproject, branch).
    """


class SectionEntry(Actions):
    """
    A kind that is a line-item inside a section of a parent record's
    markdown, with no yaml entry or id of its own (today: todo,
    decision).
    """


class Entity(Actions):
    """
    A kind with no stored record of its own -- calling one of its
    verbs triggers or mutates live session/process state instead of
    editing a yaml/markdown field (today: daemon, ctx, updr,
    worktree, spawn, temp).
    """


def dispatch(registry: dict, kind: str, action: str, *args) -> str:
    """
    Normalize `kind`, look it up in `registry`, and call its `action`
    method with `args`. Raises ValueError if `kind` isn't registered;
    the kind's own `action` method raises if it doesn't support it.
    """
    kind = normalize_identity_kind(kind)
    cls = registry.get(kind)
    if cls is None:
        raise ValueError(f"no such kind '{kind}'")
    return getattr(cls(), action)(*args)


def dispatch_kw(registry: dict, kind: str, action: str, namespace) -> str:
    """
    Like `dispatch`, but for an action whose kinds take differently-
    shaped parameters (start/stop/restart/attach/detach/refresh):
    call `action` with keyword arguments pulled from `namespace` by
    matching each of the method's own parameter names, rather than a
    fixed positional shape -- the method signature is the contract.
    """
    kind = normalize_identity_kind(kind)
    cls = registry.get(kind)
    if cls is None:
        raise ValueError(f"no such kind '{kind}'")
    method = getattr(cls(), action)
    params = inspect.signature(method).parameters
    kwargs = {
        name: getattr(namespace, name) for name in params
        if hasattr(namespace, name)
    }
    return method(**kwargs)
