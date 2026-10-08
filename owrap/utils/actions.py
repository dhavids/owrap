from .memory.records import normalize_identity_kind


class Actions:
    """
    Base for a managed kind: declares the five dispatchable actions,
    each refusing by default. A kind overrides only the ones it
    actually supports.
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
