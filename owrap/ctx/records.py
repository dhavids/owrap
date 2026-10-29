"""
Apply a context-manager dispatch's model output back to the real
context.md and to explicit project/repository memory records.
"""
import re
import time
from pathlib import Path

from ..utils.io.filelock import file_lock
from ..utils.memory.records import touch_record_last_updated
from ..utils.parser.sections import (
    extract_section, merge_log_entries, replace_section, split_top_sections,
)
from ..utils.paths import context_lock_path, get_workspace_path


def validate_output(
    output_text: str, do_context: bool, do_protocol: bool,
) -> bool:
    """
    Confirm the model's output.md is structurally usable: it parses
    into the requested top-level sections, and each section's always-
    required heading (Focus for Context, Status for Project) survived.
    """
    if not output_text.strip():
        return False
    sections = split_top_sections(output_text, ("Context",))
    if do_context:
        if "## Focus" not in sections.get("Context", ""):
            return False
    if do_protocol and not do_context:
        if (
            "# Project:" not in output_text
            and "# Subproject:" not in output_text
            and "# Repository:" not in output_text
            and output_text.strip() != "# No updates"
        ):
            return False
    return True


def apply_record_output(
    output_text, context_file, project_path, repository_paths,
    session_id, project_snapshot, event_ns=None,
    repository_snapshots=None, project_section=None,
):
    """
    Merge an explicit session's project and touched repository records.
    """
    names = ["Context"] + ([project_section] if project_section else []) + [
        f"Repository: {repo_id}" for repo_id in repository_paths
    ]
    sections = split_top_sections(output_text, tuple(names))
    if sections.get("Context"):
        merge_context(sections["Context"], context_file, session_id)
    if project_path and project_section and sections.get(project_section):
        merge_record_project(
            sections[project_section], project_path,
            project_snapshot, event_ns,
        )
    for repo_id, path in repository_paths.items():
        block = sections.get(f"Repository: {repo_id}")
        if block:
            snapshot = (
                repository_snapshots.get(repo_id)
                if repository_snapshots is not None else None
            )
            merge_record_repository(block, path, event_ns, snapshot)


def merge_record_project(block, path, original_snapshot, event_ns=None):
    """
    Update a project record while preserving its goals and notes.
    """
    with file_lock(path.with_name(path.name + ".lock")):
        if event_ns and path.exists() and path.stat().st_mtime_ns > event_ns:
            return
        text = path.read_text() if path.exists() else ""
        current_snapshot = path.read_bytes() if path.exists() else None
        status = extract_section(block, "## Status")
        if status and current_snapshot == original_snapshot:
            text = replace_section(text, "## Status", status)
        decisions = entry_lines(block, "## Decisions")
        if decisions:
            stamp = time.strftime("%Y-%m-%d %H:%M")
            lines = [f"- {stamp} — {line.removeprefix('- ').strip()}"
                     for line in decisions if line.startswith("- ")]
            text = merge_log_entries(
                text, "## Decisions", lines, cap=None, prepend=True,
                key_fn=record_decision_key,
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    touch_record_last_updated(path.parent / f"{path.parent.name}.yaml")


def merge_record_repository(block, path, event_ns=None, snapshot=None):
    """
    Add distinct architecture facts to one repository record.
    """
    with file_lock(path.with_name(path.name + ".lock")):
        if event_ns and path.exists() and path.stat().st_mtime_ns > event_ns:
            return
        if snapshot is not None and path.exists():
            if path.read_bytes() != snapshot:
                return
        text = path.read_text() if path.exists() else ""
        for heading in (
            "## Architecture", "## Components", "## Interfaces",
            "## Environment",
        ):
            entries = [
                line for line in entry_lines(block, heading)
                if line.startswith("- ")
            ]
            if entries:
                if event_ns:
                    text = replace_record_facts(text, heading, entries)
                else:
                    text = merge_log_entries(
                        text, heading, entries, cap=None, key_fn=bullet_key,
                    )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    touch_record_last_updated(path.parent / f"{path.parent.name}.yaml")


def replace_record_facts(text, heading, entries):
    current = extract_section(text, heading)
    ordered = {}
    for line in entries:
        ordered[bullet_key(line)] = line
    if current:
        kept = [
            line for line in current.splitlines()[1:]
            if not (
                line.startswith("- ") and bullet_key(line) in ordered
            )
        ]
    else:
        kept = []
    block = "\n".join([heading] + kept + list(ordered.values()))
    return replace_section(text, heading, block)


def record_decision_key(line):
    stripped = re.sub(
        r"^-\s*\d{4}-\d{2}-\d{2}(\s+\d{2}:\d{2})?\s*—\s*", "", line,
    )
    return bullet_key(stripped)


def merge_context(context_block, real_context_path, owrap_sid):
    """
    Apply the model's Context block to the real context.md.
    """
    with file_lock(context_lock_path(owrap_sid)):
        real_text = (
            real_context_path.read_text() if real_context_path.exists() else ""
        )

        for heading in ("## Focus", "## Environment"):
            new_text = extract_section(context_block, heading)
            if new_text:
                real_text = replace_section(real_text, heading, new_text)

        for heading, cap, keep_fn in (
            ("## Key Locations", 5, key_location_still_exists),
            ("## Decisions", 7, None),
            ("## How To", 3, None),
        ):
            new_lines = entry_lines(context_block, heading)
            if new_lines or keep_fn is not None:
                real_text = merge_log_entries(
                    real_text, heading, new_lines, cap=cap,
                    prepend=False, key_fn=bullet_key, keep_fn=keep_fn,
                )

        real_context_path.write_text(real_text)


def entry_lines(block, heading):
    """
    Return the non-empty entry lines under `heading` within `block`,
    excluding the heading line itself.
    """
    section = extract_section(block, heading)
    if not section:
        return []
    return [line for line in section.splitlines()[1:] if line.strip()]


def bullet_key(line: str) -> str:
    """
    Dedup key for a `- X — Y` style bullet: the `X` part.
    """
    stripped = line.strip()
    if stripped.startswith("- "):
        stripped = stripped[2:]
    return stripped.split(" — ")[0].strip().strip("`")


def key_location_still_exists(line: str) -> bool:
    """
    False only when a Key Locations bullet's leading path looks like a
    real repo path and no longer exists on disk. A token with no file
    extension is not treated as a path.
    """
    stripped = line.strip()
    if stripped.startswith("- "):
        stripped = stripped[2:]
    path_str = stripped.split(" ", 1)[0].strip("`") if stripped else ""
    if not path_str or "." not in path_str:
        return True
    workspace = get_workspace_path()
    if not workspace:
        return True
    return (Path(workspace) / path_str).exists()
