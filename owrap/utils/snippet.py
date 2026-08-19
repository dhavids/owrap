import re
import textwrap
from pathlib import Path

from ..constants import LOG_DIVIDER_WIDTH


def extract_snippet(path: Path, default: str = "") -> str:
    """
    Extract a short descriptive snippet from a plan/task file.
    """
    try:
        content = path.read_text()
    except Exception:
        return default

    content = re.sub(
        r'^## Context\nFirst read .+ before starting this task\.\n\n',
        '', content, count=1,
    )

    match = re.search(r'^## \[ACTIVE\]\s+(.+)$', content, re.MULTILINE)
    if match:
        plan_id = match.group(1).split(' — ')[0].strip()
        phase_match = re.search(r'^\*\*Phase:\*\*\s*(.+)$', content, re.MULTILINE)
        if phase_match:
            return f"{plan_id} — {phase_match.group(1).strip()}"
        return plan_id

    match = re.search(r'^## Do\s*\n+(.+)$', content, re.MULTILINE)
    if match:
        return match.group(1).strip()

    first_line = content.split("\n", 1)[0].strip()
    if first_line.startswith("#"):
        return first_line.lstrip("#").strip()

    return default


def wrap_log_text(text: str, width: int = 120) -> str:
    """
    Wrap each line of text to the given width.
    """
    return "\n".join(
        textwrap.fill(line, width=width) if line else ""
        for line in text.split("\n")
    )


def divider(label: str, width: int = LOG_DIVIDER_WIDTH) -> str:
    """
    Return a centered label surrounded by '=' dividers.
    """
    return f" {label} ".center(width, "=")
