"""
Generic markdown heading extraction/replacement.

Used by the context manager to splice a model's scoped output back into
real files (context.md / memory.md / projects.md) without the model ever
having direct access to those files itself.
"""


def _heading_level(line: str) -> int:
    return len(line) - len(line.lstrip("#"))


def extract_section(text: str, heading: str) -> str:
    """
    Return the block starting at the line exactly matching `heading` up
    to (not including) the next heading of the same or shallower level.
    Empty string if `heading` isn't found.
    """
    level = _heading_level(heading)
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.rstrip() == heading:
            start = i
            break
    if start is None:
        return ""
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("#") and _heading_level(lines[i]) <= level:
            end = i
            break
    return "\n".join(lines[start:end]).rstrip("\n")


def replace_section(text: str, heading: str, new_block: str) -> str:
    """
    Replace the section at `heading` with new_block (which must itself
    start with the same heading line). Appended at the end if `heading`
    isn't already present. Leaves exactly one blank line between the
    heading and its own content, and exactly two blank lines before
    whatever section follows.
    """
    level = _heading_level(heading)
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.rstrip() == heading:
            start = i
            break
    new_lines = new_block.rstrip("\n").splitlines()
    # Guarantee the heading-to-content gap regardless of caller formatting.
    if len(new_lines) > 1 and new_lines[1].strip():
        new_lines = [new_lines[0], ""] + new_lines[1:]
    if start is None:
        prefix = text.rstrip("\n")
        sep = "\n\n\n" if prefix else ""
        return prefix + sep + "\n".join(new_lines) + "\n"
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("#") and _heading_level(lines[i]) <= level:
            end = i
            break
    tail = lines[end:]
    sep = ["", ""] if tail else []
    return "\n".join(lines[:start] + new_lines + sep + tail).rstrip("\n") + "\n"


def merge_log_entries(
    text: str, heading: str, new_lines: list, cap: int = None,
    prepend: bool = False, key_fn=None, keep_fn=None,
) -> str:
    """
    Merge `new_lines` into the entries under `heading` in `text`, deduping
    against existing entries by `key_fn` (defaults to the whole line),
    then trimming to `cap` total by dropping the oldest. New entries land
    at the end (`prepend=False`) or the start (`prepend=True`) of the
    existing ones; `cap=None` means no trimming. `keep_fn`, if given,
    drops any existing entry it returns False for before merging — e.g.
    pruning a stale entry whose file no longer exists — even when
    `new_lines` is empty.
    """
    if key_fn is None:
        def key_fn(line):
            return line.strip()

    level = _heading_level(heading)
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.rstrip() == heading:
            start = i
            break

    if start is None:
        existing_entries = []
    else:
        end = len(lines)
        for i in range(start + 1, len(lines)):
            if lines[i].startswith("#") and _heading_level(lines[i]) <= level:
                end = i
                break
        existing_entries = [
            line for line in lines[start + 1:end] if line.strip()
        ]

    if keep_fn is not None:
        kept_entries = [line for line in existing_entries if keep_fn(line)]
    else:
        kept_entries = existing_entries
    pruned = len(kept_entries) != len(existing_entries)

    existing_keys = {key_fn(line) for line in kept_entries}
    deduped_new = [
        line for line in new_lines if key_fn(line) not in existing_keys
    ]
    if not deduped_new and not pruned:
        return text

    merged = (
        deduped_new + kept_entries if prepend
        else kept_entries + deduped_new
    )
    if cap is not None and len(merged) > cap:
        merged = merged[:cap] if prepend else merged[-cap:]

    new_block = "\n".join([heading] + merged)
    return replace_section(text, heading, new_block)


def split_top_sections(text: str, names: tuple) -> dict:
    """
    Split `text` on top-level `# <Name>` headers (Name in `names`).

    Returns {name: block_text} for each header actually present.
    """
    result = {}
    current = None
    buf = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# ") and stripped[2:].strip() in names:
            if current is not None:
                result[current] = "\n".join(buf).strip()
            current = stripped[2:].strip()
            buf = []
        elif current is not None:
            buf.append(line)
    if current is not None:
        result[current] = "\n".join(buf).strip()
    return result
