#!/usr/bin/env python3
"""
Keep the Markdown templates honest against the real CLI grammar.

`verify()` extracts every backtick-wrapped `owrap ...` example across
`templates/**/*.md` and checks it actually resolves through the real
kind/action resolver -- catches a doc describing a command that quietly
stopped existing (renamed kind, renamed action, retired verb) instead of
letting it sit stale until someone trips over it by hand.

`generate()` rewrites both "GENERATED" blocks in `self/commands.md` --
the workflow-grouped tables and the full per-kind reference -- built
straight from each kind's own `usage` dict, so neither can fall out of
sync with what a kind actually supports.

Run directly (`python3 templates/build.py`) to regenerate, or via
`deploy.py --check` (verify-only, no write) before promoting dev to
live.
"""
import contextlib
import io
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from owrap.cli import _resolve_kind_first  # noqa: E402
from owrap.kind import KIND_ALIASES, KIND_REGISTRY  # noqa: E402
from owrap.kind.dispatch import Dispatch  # noqa: E402

TEMPLATES_DIR = Path(__file__).resolve().parent
COMMANDS_MD = TEMPLATES_DIR / "self" / "commands.md"

PREFIXES = ("owrap", "~/bin/owrap", "{{BIN_DIR}}/owrap")
# A span may wrap across one prose line break (plain `\n`), but never a
# blank line (`\n\n`) -- that would mean crossing into the next paragraph
# or a fenced code block instead of just a wrapped sentence.
COMMAND_RE = re.compile(
    r"`((?:" + "|".join(re.escape(p) for p in PREFIXES) + r")(?!\w)"
    r"(?:(?!\n\n)[^`])*)`"
)

GENERATED_START = "<!-- BEGIN GENERATED: full command reference (templates/build.py) -->"
GENERATED_END = "<!-- END GENERATED: full command reference -->"

WORKFLOW_START = "<!-- BEGIN GENERATED: workflow tables (templates/build.py) -->"
WORKFLOW_END = "<!-- END GENERATED: workflow tables -->"

# Display order and heading for each `usage[action]["group"]` value.
GROUP_TITLES = {
    "session": "## Session commands",
    "record": "## Record and context commands",
    "dispatch": "## Dispatch commands",
    "server": "## Server management",
}


def _is_placeholder(token: str) -> bool:
    """
    A token is part of the fixed kind/action prefix until it looks
    like a placeholder, flag, or alternation -- `<id>`, `[name]`,
    `--flag`, `{{PLACEHOLDER}}`, `task|exec`.
    """
    return (
        token.startswith(("-", "<", "[", "{{", '"', "'"))
        or "|" in token
    )


def fixed_tokens(command: str) -> list:
    """
    Return the literal kind/action tokens of a doc command example,
    stopping at the first placeholder/flag -- e.g. `owrap task start
    --msg <text>` -> `["task", "start"]`.
    """
    tokens = command.split()
    if tokens and tokens[0] in PREFIXES:
        tokens = tokens[1:]
    fixed = []
    for token in tokens:
        if _is_placeholder(token):
            break
        fixed.append(token)
    return fixed


def verify_command(fixed: list) -> str | None:
    """
    Resolve a fixed token sequence the same way the real CLI does.
    Returns an error string, or None if it checks out.
    """
    if not fixed:
        return None
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            resolved = _resolve_kind_first(list(fixed))
    except SystemExit:
        return f"`{' '.join(fixed)}` is ambiguous -- needs an explicit kind prefix"
    if resolved is None:
        return f"`{' '.join(fixed)}` does not resolve to any kind/action"
    kind = KIND_ALIASES.get(resolved[0], resolved[0])
    cls = KIND_REGISTRY[kind]
    if len(resolved) < 2:
        return None
    action = resolved[1]
    instance = cls()
    if getattr(instance, action, None) is not None:
        return None
    if getattr(instance, f"_default_{action}", None) is not None:
        return None
    if issubclass(cls, Dispatch):
        return None
    return f"kind '{kind}' does not support action '{action}' (from `{' '.join(fixed)}`)"


def verify_file(path: Path) -> list:
    """
    Return a list of "line N: message" errors found in one file.
    Scans the whole file (not line by line) so a backtick span that
    wraps across one prose line break is still caught.
    """
    errors = []
    text = path.read_text()
    for match in COMMAND_RE.finditer(text):
        error = verify_command(fixed_tokens(match.group(1)))
        if error:
            lineno = text.count("\n", 0, match.start()) + 1
            errors.append(f"line {lineno}: {error}")
    return errors


def verify(paths: list = None) -> dict:
    """
    Verify every example across `paths` (default: every template
    Markdown file). Returns {path: [errors]} for files with failures.
    """
    paths = paths or sorted(TEMPLATES_DIR.rglob("*.md"))
    failures = {}
    for path in paths:
        errors = verify_file(path)
        if errors:
            failures[path] = errors
    return failures


def _kind_reference(kind: str, cls: type) -> str:
    usage = getattr(cls, "usage", {})
    if not usage:
        return ""
    lines = [f"### `owrap {kind}`", "", "| Action | Usage | Example |", "|---|---|---|"]
    for action, spec in usage.items():
        example = spec.get("examples", [""])[0] if spec.get("examples") else ""
        shape = spec.get("usage", "")
        full = f"owrap {kind} {action} {example}".strip()
        lines.append(f"| `{action}` | `{shape}` | `{full}` |")
    return "\n".join(lines)


def generate_commands_reference() -> str:
    """
    Build the full per-kind command reference from `KIND_REGISTRY`.
    """
    sections = []
    for kind, cls in sorted(KIND_REGISTRY.items()):
        section = _kind_reference(kind, cls)
        if section:
            sections.append(section)
    body = "\n\n\n".join(sections)
    return f"{GENERATED_START}\n## Full Command Reference\n\n{body}\n{GENERATED_END}"


def _grouped_rows() -> dict:
    """
    Collect every usage entry that declares a `group`, keyed by group,
    in `KIND_REGISTRY` order (alphabetical by kind, then declaration
    order within the kind).
    """
    rows = {group: [] for group in GROUP_TITLES}
    for kind, cls in sorted(KIND_REGISTRY.items()):
        for action, spec in getattr(cls, "usage", {}).items():
            group, purpose = spec.get("group"), spec.get("purpose")
            if group in rows and purpose:
                rows[group].append((kind, action, purpose))
    return rows


def _merge_same_purpose(rows: list) -> list:
    """
    Combine consecutive same-kind rows that share the same `purpose` into
    one `action1 / action2` row (e.g. daemon start/stop/restart).
    """
    merged = []
    for kind, action, purpose in rows:
        if merged and merged[-1][0] == kind and merged[-1][2] == purpose:
            prev_kind, prev_action, prev_purpose = merged[-1]
            merged[-1] = (prev_kind, f"{prev_action} / {action}", prev_purpose)
        else:
            merged.append((kind, action, purpose))
    return merged


def generate_workflow_tables() -> str:
    """
    Build the workflow-grouped `Command | Effect` tables straight from
    the same per-kind `usage` dicts the full reference reads, so a
    command's grouping/one-line effect can't drift from its real
    syntax independently.
    """
    rows_by_group = _grouped_rows()
    sections = []
    for group, title in GROUP_TITLES.items():
        rows = _merge_same_purpose(rows_by_group[group])
        if not rows:
            continue
        lines = [title, "", "| Command | Effect |", "|---|---|"]
        for kind, action, purpose in rows:
            lines.append(f"| `owrap {kind} {action}` | {purpose} |")
        sections.append("\n".join(lines))
    body = "\n\n\n".join(sections)
    return f"{WORKFLOW_START}\n{body}\n{WORKFLOW_END}"


def _replace_block(text: str, start: str, end: str, block: str) -> str:
    """
    Replace the `start`..`end` marked block in `text` with `block`,
    appending it instead if the markers aren't present yet.
    """
    pattern = re.compile(re.escape(start) + r".*?" + re.escape(end), re.DOTALL)
    if pattern.search(text):
        return pattern.sub(block, text)
    return text.rstrip("\n") + "\n\n\n" + block + "\n"


def generate() -> None:
    """
    Replace the GENERATED blocks in `self/commands.md` with a fresh
    workflow grouping and full command reference, both built straight
    from `KIND_REGISTRY`'s `usage` dicts.
    """
    text = COMMANDS_MD.read_text()
    text = _replace_block(
        text, WORKFLOW_START, WORKFLOW_END, generate_workflow_tables(),
    )
    text = _replace_block(
        text, GENERATED_START, GENERATED_END, generate_commands_reference(),
    )
    COMMANDS_MD.write_text(text)


def main() -> int:
    """
    `--check` only verifies (no write) -- for `deploy.py`, which must
    not mutate an already-validated, clean dev checkout. Plain runs
    (`owrap sync`, a developer running it directly) regenerate first.
    """
    check_only = "--check" in sys.argv[1:]
    if not check_only:
        generate()
    failures = verify()
    if not failures:
        verb = "verified" if check_only else "regenerated"
        print(f"build: command reference {verb}, all doc examples resolve")
        return 0
    print("build: stale command examples found —")
    for path, errors in failures.items():
        print(f"\n{path.relative_to(ROOT)}:")
        for error in errors:
            print(f"  {error}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
