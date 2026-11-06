"""
Branch origin tags on repository memory entries: a trailing
`[<branch>@<commit>]` where the branch or commit differs from the
previous entry, `[@<commit>]` where only the commit differs, and
`[base]` where a base-checkout entry follows a branch one.
"""
import json
import re
import subprocess

from ..utils.parser.sections import extract_section
from ..utils.session.resolver import _parse, session_file

TAG = re.compile(r"\s*\[(?:([^\]\s@]+)?@([0-9a-f]+)|base)\]\s*$")


def strip_tag(line: str) -> str:
    """
    Return `line` without its trailing origin tag.
    """
    return TAG.sub("", line)


def branch_origin(session_id: str, repo_id: str):
    """
    Return the (branch ref, short commit) a branch session works on in
    `repo_id`, or None when the session is not on a branch of it.
    """
    data = _parse(session_file(session_id))
    entry = json.loads(data.get("branch_worktrees") or "{}").get(repo_id)
    if not entry:
        return None
    result = subprocess.run(
        ["git", "-C", entry["path"], "rev-parse", "--short", "HEAD"],
        capture_output=True, text=True, check=False,
    )
    commit = result.stdout.strip() or entry["base_commit"][:7]
    return entry["ref"], commit


def next_tags(text: str, origin, headings) -> dict:
    """
    Return the tag a new first entry would get under each of `headings`
    in the record `text`, empty where none is needed.
    """
    tags = {}
    for heading in headings:
        section = extract_section(text, heading) or ""
        tags[heading] = _tag(_state(section.splitlines()[1:]), origin).strip()
    return tags


def tag_entries(entries: list, existing: list, origin, key_fn) -> list:
    """
    Return the new `entries` with origin tags following the state the
    `existing` entries leave. Entries already present keep no tag.
    """
    state = _state(existing)
    keys = {key_fn(line) for line in existing}
    tagged = []
    for line in entries:
        line = strip_tag(line)
        if key_fn(line) in keys:
            tagged.append(line)
            continue
        tagged.append(line + _tag(state, origin))
        state = origin
    return tagged


def missing_tags(
    text: str, known: set, origins: list, headings, key_fn,
) -> list:
    """
    Return (heading, line, tag) for each new bullet in the record `text`
    that has no origin tag although every origin in `origins` requires
    one. A bullet is new when `key_fn` of it is not in `known`.
    """
    missing = []
    for heading in headings:
        section = extract_section(text, heading) or ""
        state = None
        for line in section.splitlines()[1:]:
            if not line.startswith("- "):
                continue
            tags = [_tag(state, origin).strip() for origin in origins]
            if key_fn(line) not in known and not TAG.search(line) and all(tags):
                missing.append((heading, line, tags[-1]))
                state = origins[-1]
                continue
            state = _advance(state, line)
    return missing


def _advance(state, line: str):
    match = TAG.search(line)
    if not match:
        return state
    if match.group(2) is None:
        return None
    return (match.group(1) or (state[0] if state else ""), match.group(2))


def _state(lines: list):
    state = None
    for line in lines:
        state = _advance(state, line)
    return state


def _tag(state, origin) -> str:
    if origin is None:
        return " [base]" if state else ""
    ref, commit = origin
    if state is None or state[0] != ref:
        return f" [{ref}@{commit}]"
    if state[1] != commit:
        return f" [@{commit}]"
    return ""
