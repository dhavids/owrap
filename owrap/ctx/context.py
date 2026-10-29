"""
context.md's own structure: the section skeleton every session's
context file shares, the Session header fields synced onto it, and
the per-section line caps that keep it from growing unbounded. This
is the one place that defines what a context.md looks like -- the
entry point for creating or resyncing one, whoever the caller is
(a brand-new session, a refresh, a dispatch). `records.py` owns the
file's model-driven *content* merges (Focus/Decisions/etc from a
dispatch), not its structure.
"""
import re
from pathlib import Path

SECTIONS = (
    "## Focus", "## Active Plan", "## Key Locations", "## Decisions",
    "## Environment", "## How To", "## Frequent Files", "## Recent",
)

SECTION_LINE_CAPS = {
    "## Focus": 5,
    "## Active Plan": 3,
    "## Key Locations": 5,
    "## Decisions": 7,
    "## Environment": 3,
    "## How To": 3,
    "## Frequent Files": 5,
    "## Recent": 5,
}


# Skeleton & Header

def skeleton(fields: dict) -> str:
    """
    Render a brand-new context.md: a `## Session` header with
    `fields` (in order), then every section, empty.
    """
    header = "".join(f"{name}: {value}\n" for name, value in fields.items())
    sections = "".join(f"{section}\n\n" for section in SECTIONS)
    return f"## Session\n\n{header}\n{sections}"


def ensure(path: Path, fields: dict) -> None:
    """
    Create `path` with a fresh skeleton if it doesn't already exist.
    """
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(skeleton(fields))


def sync_header(path: Path, fields: dict, drop: tuple = ()) -> None:
    """
    Create `path` fresh if missing; otherwise resync its `## Session`
    header: replace each of `fields`' values if already present,
    insert it right after the heading if not, and drop any field
    named in `drop` entirely (e.g. `server`/`plan` once the runner
    is disabled). Never touches anything below the header.
    """
    if not path.exists():
        ensure(path, fields)
        return
    text = path.read_text()
    for name in drop:
        text = re.sub(rf"^{name}:.*\n", "", text, flags=re.MULTILINE)
    for field, value in fields.items():
        if re.search(rf"^{field}:.*$", text, re.MULTILINE):
            text = re.sub(
                rf"^{field}:.*$", f"{field}: {value}",
                text, flags=re.MULTILINE,
            )
        else:
            text = re.sub(
                r"^(## Session\s*\n)", rf"\1{field}: {value}\n",
                text, count=1, flags=re.MULTILINE,
            )
    path.write_text(text)


# Section Caps

def cap_sections(path: Path) -> None:
    """
    Trim every section in `path` down to its line cap in
    `SECTION_LINE_CAPS`, oldest entries first. Silently no-ops on
    any read/write failure -- capping is best-effort housekeeping,
    never worth failing the caller over.
    """
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return
    new_lines = []
    current_section = None
    section_count = 0
    for line in lines:
        if line.startswith("## "):
            current_section = line.strip()
            section_count = 0
            new_lines.append(line)
        elif current_section in SECTION_LINE_CAPS:
            if line.strip():
                section_count += 1
                if section_count <= SECTION_LINE_CAPS[current_section]:
                    new_lines.append(line)
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)
    try:
        path.write_text("\n".join(new_lines) + "\n")
    except OSError:
        pass
