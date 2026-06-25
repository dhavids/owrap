import hashlib
import json
import re
from pathlib import Path

from .paths import context_path, _read_config, get_plan_path
from ..constants import NO_CONTEXT_MSG, NO_AREA_SECTION_MSG, CTX_DUE_MSG, UPDR_DUE_MSG, UPDR_DUE_PRECOMPACT_MSG

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

    counters = _read_counters(session_id)
    cp = context_path(session_id)
    config = _read_config()
    research_root = config.get("research_root", "")
    plan_path = get_plan_path(session_id)

    # Reset: context mtime newer than recorded injection time
    ctx_mtime = counters.get("ctx_mtime_at_injection")
    if ctx_mtime is not None and cp.exists():
        try:
            if cp.stat().st_mtime > ctx_mtime:
                counters["orun_count"] = 0
                del counters["ctx_mtime_at_injection"]
        except OSError:
            pass

    # Reset: area hash changed (updr was run, memory/projects updated)
    if research_root and research:
        base = Path(research_root)
        memory_path = base / "memory" / f"{research}.md"
        projects_path = base / "projects" / f"{research}.md"
        mem_text = _get_area_section_text(memory_path, area)
        proj_text = _get_area_section_text(projects_path, area)
        current_hash = hashlib.sha256((mem_text + "\n" + proj_text).encode()).hexdigest()
        area_hashes = counters.get("area_hash", {})
        stored_hash = area_hashes.get(area)
        if stored_hash is not None and current_hash != stored_hash:
            counters["plan_count"] = 0
            counters["marked_steps_baseline"] = _count_marked_steps(plan_path)
            area_hashes.pop(area, None)
            counters["area_hash"] = area_hashes

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

    # Determine if this dispatch should be excluded from counts
    skip_orun = False
    if input_path is not None:
        try:
            if "sync_task" in input_path.name or "_precompact" in input_path.name:
                skip_orun = True
            elif input_path.exists():
                first_line = input_path.read_text(encoding="utf-8").split("\n", 1)[0].strip()
                if first_line in ("# Context Update", "# Update Protocol"):
                    skip_orun = True
                    counters["orun_count"] = 0
                    counters["updr_orun_count"] = 0
        except OSError:
            pass

    # Increment counters
    counters.setdefault("orun_count", 0)
    counters.setdefault("updr_orun_count", 0)
    counters.setdefault("plan_count", 0)
    counters.setdefault("marked_steps_baseline", 0)
    counters.setdefault("precompact_count", 0)
    counters.setdefault("last_updr_precompact", 0)

    if kind == "task" and not skip_orun:
        counters["orun_count"] += 1
        counters["updr_orun_count"] += 1
    elif kind == "exec":
        counters["plan_count"] += 1
    elif kind == "precompact":
        counters["precompact_count"] += 1

    marked_steps = _count_marked_steps(plan_path) - counters.get("marked_steps_baseline", 0)

    ctx_update_every_orun = int(config.get("ctx_update_every_orun", 3))
    updr_every_plans = int(config.get("updr_every_plans", 2))
    updr_every_steps = int(config.get("updr_every_steps", 15))
    updr_every_precompact = int(config.get("updr_every_precompact", 3))
    updr_every_orun = int(config.get("updr_every_orun", 15))

    orun_count = counters["orun_count"]
    updr_orun_count = counters["updr_orun_count"]
    plan_count = counters["plan_count"]

    ctx_due = orun_count >= ctx_update_every_orun or plan_count >= updr_every_plans or marked_steps >= updr_every_steps
    updr_due = plan_count >= updr_every_plans or marked_steps >= updr_every_steps or updr_orun_count >= updr_every_orun

    messages = []

    if ctx_due:
        try:
            counters["ctx_mtime_at_injection"] = cp.stat().st_mtime
        except OSError:
            pass
        messages.append(CTX_DUE_MSG.format(
            orun=orun_count, max_orun=ctx_update_every_orun,
            plan=plan_count, max_plan=updr_every_plans,
            steps=marked_steps, max_steps=updr_every_steps,
        ))

    if updr_due:
        if research_root and research:
            base = Path(research_root)
            memory_path = base / "memory" / f"{research}.md"
            projects_path = base / "projects" / f"{research}.md"
            mem_text = _get_area_section_text(memory_path, area)
            proj_text = _get_area_section_text(projects_path, area)
            current_hash = hashlib.sha256((mem_text + "\n" + proj_text).encode()).hexdigest()
        else:
            current_hash = ""
        counters.setdefault("area_hash", {})
        counters["last_updr_precompact"] = counters["precompact_count"]
        counters["area_hash"][area] = current_hash
        counters["orun_count"] = 0
        counters["updr_orun_count"] = 0
        counters["plan_count"] = 0
        if not ctx_due:
            try:
                counters["ctx_mtime_at_injection"] = cp.stat().st_mtime
            except OSError:
                pass
            messages.append(CTX_DUE_MSG.format(
                orun=orun_count, max_orun=ctx_update_every_orun,
                plan=plan_count, max_plan=updr_every_plans,
                steps=marked_steps, max_steps=updr_every_steps,
            ))
        messages.append(UPDR_DUE_MSG.format(
            area=area, plan=plan_count, max_plan=updr_every_plans,
            steps=marked_steps, max_steps=updr_every_steps,
            orun=updr_orun_count, max_orun=updr_every_orun,
        ))

    precompact_count = counters["precompact_count"]
    last_updr_precompact = counters.get("last_updr_precompact", 0)
    precompact_updr_due = (
        kind == "precompact"
        and precompact_count > 0
        and not updr_due
        and (precompact_count - last_updr_precompact) >= updr_every_precompact
    )
    if precompact_updr_due:
        counters["last_updr_precompact"] = precompact_count
        counters["orun_count"] = 0
        counters["updr_orun_count"] = 0
        counters["plan_count"] = 0
        try:
            counters["ctx_mtime_at_injection"] = cp.stat().st_mtime
        except OSError:
            pass
        messages.append(CTX_DUE_MSG.format(
            orun=orun_count, max_orun=ctx_update_every_orun,
            plan=plan_count, max_plan=updr_every_plans,
            steps=marked_steps, max_steps=updr_every_steps,
        ))
        messages.append(UPDR_DUE_PRECOMPACT_MSG.format(precompact_count=precompact_count))

    _write_counters(session_id, counters)

    if messages:
        return "\n\n".join(messages)
    return None
