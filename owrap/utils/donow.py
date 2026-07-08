import hashlib
import json
import re
from pathlib import Path

from .paths import context_path, _read_config, get_plan_path
from ..constants import NO_CONTEXT_MSG, NO_AREA_SECTION_MSG

COUNTERS_DIR = Path.home() / ".owrap" / "sessions"


def _counters_path(session_id: str) -> Path:
    return COUNTERS_DIR / f"{session_id}.counters.json"


def _read_counters(session_id: str) -> dict:
    p = _counters_path(session_id)
    if p.exists():
        try:
            with open(p) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _write_counters(session_id: str, data: dict):
    p = _counters_path(session_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w") as f:
        json.dump(data, f)


def _get_area_section_text(file_path: Path, area: str) -> str:
    if not file_path.exists():
        return ""
    text = file_path.read_text()
    lines = text.splitlines()
    pattern = f"## {area}"
    start_idx = None
    for i, line in enumerate(lines):
        if line.strip() == pattern:
            start_idx = i
            break
    if start_idx is None:
        return ""
    section_lines = []
    for i in range(start_idx, len(lines)):
        if i > start_idx and lines[i].startswith("## "):
            break
        section_lines.append(lines[i])
    return "\n".join(section_lines)


def _hash_area_section(file_path: Path, area: str) -> str:
    text = _get_area_section_text(file_path, area)
    if not text:
        return ""
    return hashlib.sha256(text.encode()).hexdigest()


def _count_marked_steps(plan_path: Path) -> int:
    if not plan_path.exists():
        return 0
    plan_text = plan_path.read_text()
    count = 0
    in_active = False
    for line in plan_text.splitlines():
        if "## [ACTIVE]" in line:
            in_active = True
        elif line.startswith("## ") and in_active:
            in_active = False
        elif in_active and re.match(r"\d+\. \[x\]", line):
            count += 1
    return count


def check_donow(manager, session_id: str, area: str, research: str, kind: str, input_path=None) -> str | None:
    if not area:
        return None

    cp = context_path(session_id)
    config = _read_config()
    research_root = config.get("research_root", "")

    # Context file missing
    if kind != "precompact" and not cp.exists():
        return NO_CONTEXT_MSG.format(sid=session_id)

    # Area section missing in memory or projects
    if kind != "precompact" and research_root and research:
        base = Path(research_root)
        memory_path = base / "memory" / f"{research}.md"
        projects_path = base / "projects" / f"{research}.md"
        mem_text = _get_area_section_text(memory_path, area)
        proj_text = _get_area_section_text(projects_path, area)
        if not mem_text or not proj_text:
            return NO_AREA_SECTION_MSG.format(area=area)

    return None
