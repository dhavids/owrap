import json
import re
import shutil
from pathlib import Path
from .utils.paths import (
    CONFIGS_DIR, OWRAP_HOME, TEMPLATES_DIR,
    get_workspace_config, staged_dir,
)


PLACEHOLDER_RE = re.compile(r"\{\{([A-Z_]+)\}\}")

# Matches only innermost {{IF:FLAG}}...{{ENDIF}} blocks (no nested {{IF:}} inside), so
# process_conditionals can resolve nested blocks from the inside out.
COND_RE = re.compile(r"\{\{IF:([A-Z_]+)\}\}((?:(?!\{\{IF:)[\s\S])*?)\{\{ENDIF\}\}")


def _tilde_relative(path: str) -> str:
    home = str(Path.home())
    if path.startswith(home):
        return "~" + path[len(home):]
    return path


def resolve_placeholders(config: dict, workspace_name: str) -> dict:
    """
    Build the full placeholder → value map from workspace config + derived values.
    """
    workspace = config.get("workspace", "")
    research_root = config.get("research_root") or (
        f"{workspace}/docs/research" if workspace else ""
    )
    bin_dir = config.get("bin_dir") or str(Path.home() / "bin")
    owrap_docs = str(OWRAP_HOME / "docs")
    owrap_home = str(OWRAP_HOME)
    oread = bool(config.get("oread", True))
    return {
        "WORKSPACE": workspace,
        "RESEARCH_ROOT": research_root,
        "BIN_DIR": bin_dir,
        "PROJECT_NAME": workspace_name,
        "OWRAP_DOCS": owrap_docs,
        "OWRAP_HOME": owrap_home,
        "WORKSPACE_TILDE": _tilde_relative(workspace),
        "RESEARCH_ROOT_TILDE": _tilde_relative(research_root),
        "PERMIT_MATCHER": "Bash|Write|Edit|Read" if oread else "Bash|Write|Edit",
        "REFRESH_REREAD": "`CLAUDE.md`",
    }


def substitute(text: str, placeholders: dict) -> str:
    def _r(m):
        k = m.group(1)
        return placeholders.get(k, m.group(0))
    return PLACEHOLDER_RE.sub(_r, text)


def process_conditionals(text: str, flags: dict) -> str:
    """
    Strip {{IF:FLAG}}...{{ENDIF}} blocks where flags[FLAG] is falsy.
    Keep block contents otherwise. Supports nesting: repeatedly resolves
    innermost blocks until none remain.
    """
    def _r(m):
        flag = m.group(1)
        content = m.group(2)
        return content if flags.get(flag) else ""
    prev = None
    while prev != text:
        prev = text
        text = COND_RE.sub(_r, text)
    return text


def resolve_flags(config: dict) -> dict:
    """
    Build the boolean flag map for conditional template blocks.
    """
    oread = bool(config.get("oread", True))
    owrap_enabled = bool(config.get("owrap_enabled", True))
    return {
        "OREAD": oread,
        "NO_OREAD": not oread,
        "ALLOW_ALL": bool(config.get("allow_all", False)),
        "OWRAP_ENABLED": owrap_enabled,
        "OWRAP_DISABLED": not owrap_enabled,
    }


def _group_active(group: dict, flags: dict) -> bool:
    cond = group.get("condition")
    return flags.get(cond, False) if cond else True


def load_permission_groups(filename: str) -> list:
    """
    Load groups from templates/<filename> (allow.json or deny.json).
    """
    path = TEMPLATES_DIR / filename
    if not path.exists():
        return []
    return json.loads(path.read_text()).get("groups", [])


def render_rule_array(
    groups: list, flags: dict, placeholders: dict,
    indent: int = 6, exclude_tools: set = None,
) -> str:
    """
    Render the flat list of permission rules (filtered by flags,
    placeholders resolved) as a JSON array literal.
    """
    rules = []
    for group in groups:
        if not _group_active(group, flags):
            continue
        for rule in group.get("rules", []):
            tool = rule.split("(", 1)[0] if "(" in rule else rule
            if exclude_tools and tool in exclude_tools:
                continue
            rules.append(substitute(rule, placeholders))
    bare_tools = {r for r in rules if "(" not in r}
    rules = [r for r in rules if "(" not in r or r.split("(", 1)[0] not in bare_tools]
    if not rules:
        return "[]"
    pad = " " * indent
    items = ",\n".join(f'{pad}"{r}"' for r in rules)
    return f"[\n{items}\n{' ' * (indent - 2)}]"


def render_allowed_section(
    groups: list, flags: dict, placeholders: dict, section: str,
) -> str:
    """
    Render the '## Allowed' markdown bullet list for `section`
    ('commands' or 'files').
    """
    lines = []
    for group in groups:
        display = group.get("display")
        if not display or display.get("section") != section:
            continue
        if not _group_active(group, flags):
            continue
        lines.append("- " + substitute(display["text"], placeholders))
    return "\n".join(lines)


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


def _strip_marker_block(dest_path: Path, marker: str):
    """
    Remove an existing owrap marker block from dest_path if present.
    """
    if not dest_path.exists():
        return
    open_marker = f"<!-- owrap:{marker} -->"
    close_marker = f"<!-- /owrap:{marker} -->"
    existing = dest_path.read_text()
    open_idx = existing.find(open_marker)
    if open_idx < 0:
        return
    close_idx = existing.find(close_marker, open_idx)
    if close_idx < 0:
        return
    before = existing[:open_idx]
    after = existing[close_idx + len(close_marker):]
    dest_path.write_text(before + after.lstrip("\n"))


def stage_all(workspace_name: str) -> Path:
    """
    Read workspace config, copy all templates to staged dir with
    conditionals processed and placeholders substituted. Then merge
    planner into CLAUDE.md and executor into AGENTS.md in the workspace.
    Returns staged dir.
    """
    config = get_workspace_config(workspace_name)
    placeholders = resolve_placeholders(config, workspace_name)
    flags = resolve_flags(config)

    allow_groups = load_permission_groups("allow.json")
    matcher_tools = (
        {"Bash", "Write", "Edit"}
        | ({"Read"} if flags.get("OREAD") else set())
    )
    placeholders["ALLOW_RULES"] = render_rule_array(
        allow_groups, flags, placeholders, exclude_tools=matcher_tools,
    )
    placeholders["ALLOWED_COMMANDS"] = render_allowed_section(
        allow_groups, flags, placeholders, "commands",
    )
    placeholders["ALLOWED_FILES"] = render_allowed_section(
        allow_groups, flags, placeholders, "files",
    )

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


    # Generate permit.json — consumed by `owrap p`

    permit_rules = []
    for group in allow_groups:
        if _group_active(group, flags):
            for rule in group.get("rules", []):
                permit_rules.append(substitute(rule, placeholders))
    bin_dir = placeholders.get("BIN_DIR", str(Path.home() / "bin"))
    orun_cmd = _tilde_relative(str(Path(bin_dir).expanduser() / "orun"))
    permit_path = CONFIGS_DIR / f"{workspace_name}_permit.json"
    permit_data = {"orun_cmd": orun_cmd, "rules": permit_rules}
    if flags.get("OWRAP_DISABLED"):
        permit_data["allow_all"] = True
    permit_path.write_text(json.dumps(permit_data, indent=2))


    # Merge planner.md into CLAUDE.md and executor.md into AGENTS.md

    ws = config.get("workspace")
    if ws:
        ws_path = Path(ws)
        planner_staged = out_dir / "planner.md"
        executor_staged = out_dir / "executor.md"
        self_staged = out_dir / "self.md"
        if planner_staged.exists():
            merge_into_workspace_file(
                ws_path / "CLAUDE.md", planner_staged.read_text(),
                "planner",
            )
            _strip_marker_block(ws_path / "AGENTS.md", "planner")
        if executor_staged.exists():
            merge_into_workspace_file(
                ws_path / "AGENTS.md", executor_staged.read_text(),
                "executor",
            )
        if self_staged.exists():
            research_root = config.get("research_root") or (
                f"{ws}/docs/research"
            )
            merge_into_workspace_file(
                Path(research_root) / "self.md",
                self_staged.read_text(),
                "self",
            )

    return out_dir
