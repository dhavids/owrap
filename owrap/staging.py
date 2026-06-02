import re
import shutil
from pathlib import Path
from .utils.paths import TEMPLATES_DIR, staged_dir, get_workspace_config


PLACEHOLDER_RE = re.compile(r"\{\{([A-Z_]+)\}\}")


def resolve_placeholders(config: dict, workspace_name: str) -> dict:
    """Build the full placeholder → value map from workspace config + derived values."""
    import os
    workspace = config.get("workspace", "")
    research_root = config.get("research_root") or (f"{workspace}/docs/research" if workspace else "")
    changes_dir = f"{workspace}/docs/changes" if workspace else ""
    bin_dir = config.get("bin_dir") or str(Path.home() / "bin")
    owrap_docs = str(Path.home() / ".owrap" / "docs")
    owrap_home = str(Path.home() / ".owrap")
    return {
        "WORKSPACE": workspace,
        "RESEARCH_ROOT": research_root,
        "CHANGES_DIR": changes_dir,
        "BIN_DIR": bin_dir,
        "PROJECT_NAME": workspace_name,
        "OWRAP_DOCS": owrap_docs,
        "OWRAP_HOME": owrap_home,
    }


def substitute(text: str, placeholders: dict) -> str:
    def _r(m):
        k = m.group(1)
        return placeholders.get(k, m.group(0))
    return PLACEHOLDER_RE.sub(_r, text)


COND_RE = re.compile(r"\{\{IF:([A-Z_]+)\}\}(.*?)\{\{ENDIF\}\}", re.DOTALL)


def process_conditionals(text: str, flags: dict) -> str:
    """Strip {{IF:FLAG}}...{{ENDIF}} blocks where flags[FLAG] is falsy. Keep block contents otherwise."""
    def _r(m):
        flag = m.group(1)
        content = m.group(2)
        return content if flags.get(flag) else ""
    return COND_RE.sub(_r, text)


def resolve_flags(config: dict) -> dict:
    """Build the boolean flag map for conditional template blocks."""
    oread = bool(config.get("oread", True))
    return {
        "OREAD": oread,
        "NO_OREAD": not oread,
        "ALLOW_ALL": bool(config.get("allow_all", False)),
    }


def merge_into_workspace_file(dest_path: Path, content: str, marker: str):
    """Merge content into dest_path wrapped in owrap markers.

    Marker open: ``<!-- owrap:<marker> -->``  close: ``<!-- /owrap:<marker> -->``
    - If dest doesn't exist: create with marker-wrapped content.
    - If dest exists and contains open marker: replace only the block between markers.
    - If dest exists but has no markers: prepend marker-wrapped content to existing file.
    """
    open_marker = f"<!-- owrap:{marker} -->"
    close_marker = f"<!-- /owrap:{marker} -->"
    wrapped = f"{open_marker}\n{content}\n{close_marker}\n"

    dest_path.parent.mkdir(parents=True, exist_ok=True)

    if not dest_path.exists():
        dest_path.write_text(wrapped)
        return

    existing = dest_path.read_text()
    open_idx = existing.find(open_marker)
    if open_idx >= 0:
        close_idx = existing.find(close_marker, open_idx)
        if close_idx >= 0:
            before = existing[:open_idx]
            after = existing[close_idx + len(close_marker):]
            dest_path.write_text(before + wrapped + after.lstrip("\n"))
            return
    # No markers found — prepend
    dest_path.write_text(wrapped + existing)


def stage_all(workspace_name: str) -> Path:
    """Read workspace config, copy all templates to ~/.owrap/staged/<workspace_name>/ with conditionals processed and placeholders substituted. Then merge planner→CLAUDE.md and executor→AGENTS.md into the workspace. Returns staged dir."""
    config = get_workspace_config(workspace_name)
    placeholders = resolve_placeholders(config, workspace_name)
    flags = resolve_flags(config)
    out_dir = staged_dir(workspace_name)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for tpl in TEMPLATES_DIR.iterdir():
        if not tpl.is_file():
            continue
        text = tpl.read_text()
        text = process_conditionals(text, flags)
        (out_dir / tpl.name).write_text(substitute(text, placeholders))

    # Merge planner.md → workspace/CLAUDE.md and executor.md → workspace/AGENTS.md
    ws = config.get("workspace")
    if ws:
        ws_path = Path(ws)
        planner_staged = out_dir / "planner.md"
        executor_staged = out_dir / "executor.md"
        if planner_staged.exists():
            merge_into_workspace_file(ws_path / "CLAUDE.md", planner_staged.read_text(), "planner")
        if executor_staged.exists():
            merge_into_workspace_file(ws_path / "AGENTS.md", executor_staged.read_text(), "executor")

    return out_dir
