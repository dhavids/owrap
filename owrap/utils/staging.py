import json
import re
import shlex
import shutil
from pathlib import Path

from .paths import (
    CONFIGS_DIR, OWRAP_HOME, TEMPLATES_DIR,
    get_workspace_config, staged_dir,
)


PLACEHOLDER_RE = re.compile(r"\{\{([A-Z_]+)\}\}")

# Matches only innermost {{IF:FLAG}}...{{ENDIF}} blocks (no nested {{IF:}} inside), so
# process_conditionals can resolve nested blocks from the inside out.
COND_RE = re.compile(r"\{\{IF:([A-Z_]+)\}\}((?:(?!\{\{IF:)[\s\S])*?)\{\{ENDIF\}\}")
ROLE_FILE_NAMES = ("CLAUDE.md", "AGENTS.md")
HARNESS_FILES = {
    "claude": "CLAUDE.md",
    "codex": "AGENTS.md",
    "opencode": "AGENTS.md",
}
DEFAULT_ROLE_HARNESSES = {
    "planner": ["claude"],
    "executor": ["opencode"],
}
INSTRUCTION_SECTIONS = ("Planner", "Executor", "Self")
MANAGED_BLOCK_RE = re.compile(
    r"<!-- owrap:([a-z-]+) -->[\s\S]*?<!-- /owrap:\1 -->\n?",
)


def resolve_role_files(config: dict) -> dict:
    """
    Resolve the workspace files selected for each role.
    """
    harnesses = config.get("role_harnesses") or {}
    configured = config.get("role_files") or {}
    if not isinstance(harnesses, dict):
        raise ValueError("role_harnesses must be an object")
    if not isinstance(configured, dict):
        raise ValueError("role_files must be an object")
    result = {}
    for role, default in DEFAULT_ROLE_HARNESSES.items():
        if role in harnesses:
            selected = harnesses[role]
            if not isinstance(selected, list) or not selected:
                raise ValueError(f"role_harnesses.{role} must be a nonempty list")
            if any(name not in HARNESS_FILES for name in selected):
                raise ValueError(
                    f"role_harnesses.{role} must use claude, codex, or opencode"
                )
            names = [HARNESS_FILES[name] for name in selected]
        else:
            names = configured.get(
                role, [HARNESS_FILES[name] for name in default],
            )
        if not isinstance(names, list) or not names:
            raise ValueError(f"role_files.{role} must be a nonempty list")
        if any(name not in ROLE_FILE_NAMES for name in names):
            raise ValueError(f"role_files.{role} must use CLAUDE.md or AGENTS.md")
        result[role] = list(dict.fromkeys(names))
    return result


def _tilde_relative(path: str) -> str:
    home = str(Path.home())
    if path.startswith(home):
        return "~" + path[len(home):]
    return path


def _executable(bin_dir: str, name: str) -> str:
    directory = Path(bin_dir).expanduser()
    path = directory / name
    if directory == Path.home() / "bin":
        return f"~/bin/{name}"
    return shlex.quote(str(path))


def resolve_placeholders(config: dict, workspace_name: str) -> dict:
    """
    Build the full placeholder → value map from workspace config + derived values.
    """
    workspace = config.get("workspace", "")
    docs_root = config.get("docs_root") or (
        f"{workspace}/docs/research" if workspace else ""
    )
    bin_dir = config.get("bin_dir") or str(Path.home() / "bin")
    owrap_home = str(OWRAP_HOME)
    self_path = str(staged_dir(workspace_name) / "self.md")
    role_files = resolve_role_files(config)
    return {
        "WORKSPACE": workspace,
        "DOCS_ROOT": docs_root,
        "RESEARCH_ROOT": docs_root,
        "BIN_DIR": bin_dir,
        "PROJECT_NAME": workspace_name,
        "OWRAP_HOME": owrap_home,
        "SELF_PATH": self_path,
        "WORKSPACE_TILDE": _tilde_relative(workspace),
        "DOCS_ROOT_TILDE": _tilde_relative(docs_root),
        "RESEARCH_ROOT_TILDE": _tilde_relative(docs_root),
        "SELF_PATH_TILDE": _tilde_relative(self_path),
        "REFRESH_REREAD": f"`{role_files['planner'][0]}`",
        "PLANNER_MANUAL_PATH": str(Path(workspace) / role_files["planner"][0]),
    }


def read_instruction_sections(path: Path) -> dict[str, str]:
    """
    Read the Planner, Executor, and Self sections from instruction.md.
    """
    sections = {name: "" for name in INSTRUCTION_SECTIONS}
    if not path.exists():
        return sections
    current = None
    lines = {name: [] for name in INSTRUCTION_SECTIONS}
    for line in path.read_text().splitlines():
        match = re.match(r"^## (Planner|Executor|Self)\s*$", line)
        if match:
            current = match.group(1)
            continue
        if line.startswith("## "):
            current = None
        elif current:
            lines[current].append(line)
    for name, content in lines.items():
        sections[name] = "\n".join(content).strip()
    return sections


def _write_instruction_sections(path: Path, sections: dict[str, str]):
    content = ["# Workspace Instructions"]
    for name in INSTRUCTION_SECTIONS:
        content.extend(["", f"## {name}"])
        text = sections.get(name, "").strip()
        if text:
            content.extend(["", text])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(content).rstrip() + "\n")


def _unmanaged_content(path: Path) -> str:
    if not path.exists():
        return ""
    return MANAGED_BLOCK_RE.sub("", path.read_text()).strip()


def _append_instruction(sections: dict[str, str], name: str, content: str):
    content = content.strip()
    if not content or content in sections[name]:
        return
    sections[name] = "\n\n".join(
        part for part in (sections[name], content) if part
    )


def _insert_instruction_content(path: Path, name: str, content: str):
    content = content.strip()
    if not content:
        return
    text = path.read_text()
    heading = re.search(rf"^## {re.escape(name)}\s*$", text, re.MULTILINE)
    if not heading:
        path.write_text(f"{text.rstrip()}\n\n## {name}\n\n{content}\n")
        return
    next_heading = re.search(r"^## .+$", text[heading.end():], re.MULTILINE)
    end = heading.end() + next_heading.start() if next_heading else len(text)
    before = text[:end].rstrip()
    after = text[end:].lstrip("\n")
    merged = f"{before}\n\n{content}\n"
    if after:
        merged += f"\n{after}"
    path.write_text(merged)


def _retain_managed_blocks(path: Path):
    if not path.exists():
        return
    blocks = [match.group(0).strip() for match in MANAGED_BLOCK_RE.finditer(
        path.read_text(),
    )]
    path.write_text("\n\n".join(blocks) + ("\n" if blocks else ""))


def _migrate_instructions(docs_root: Path, workspace: Path | None) -> Path:
    instruction_path = docs_root / "instruction.md"
    sections = read_instruction_sections(instruction_path)
    additions = {name: [] for name in INSTRUCTION_SECTIONS}
    role_paths = []

    if workspace:
        for filename, section in (
            ("CLAUDE.md", "Planner"),
            ("AGENTS.md", "Executor"),
        ):
            path = workspace / filename
            unmanaged = _unmanaged_content(path)
            if unmanaged:
                if unmanaged not in sections[section]:
                    additions[section].append(unmanaged)
                    _append_instruction(sections, section, unmanaged)
                role_paths.append(path)

    legacy_self = docs_root / "self.md"
    unmanaged = _unmanaged_content(legacy_self)
    if unmanaged:
        if unmanaged not in sections["Self"]:
            additions["Self"].append(unmanaged)
            _append_instruction(sections, "Self", unmanaged)
    legacy_pages = docs_root / "self"
    legacy_page_paths = []
    if legacy_pages.exists():
        for page in sorted(legacy_pages.rglob("*.md")):
            unmanaged = _unmanaged_content(page)
            if unmanaged:
                if unmanaged not in sections["Self"]:
                    additions["Self"].append(unmanaged)
                    _append_instruction(sections, "Self", unmanaged)
            legacy_page_paths.append(page)

    if not instruction_path.exists():
        _write_instruction_sections(instruction_path, sections)
    else:
        for name, content in additions.items():
            if content:
                _insert_instruction_content(
                    instruction_path, name, "\n\n".join(content),
                )

    for path in role_paths:
        _retain_managed_blocks(path)
    if legacy_self.exists():
        legacy_self.unlink()
    for page in legacy_page_paths:
        page.unlink()
    if legacy_pages.exists():
        for directory in sorted(legacy_pages.rglob("*"), reverse=True):
            if directory.is_dir() and not any(directory.iterdir()):
                directory.rmdir()
        if not any(legacy_pages.iterdir()):
            legacy_pages.rmdir()
    return instruction_path


def _add_workspace_instructions(path: Path, content: str):
    content = content.strip()
    if not content or not path.exists():
        return
    base = path.read_text().rstrip()
    path.write_text(f"{base}\n\n## Workspace Instructions\n\n{content}\n")


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

    Stripped blocks can leave runs of blank lines behind at their old
    boundary; these are collapsed to a single blank line between sections.
    """
    def _r(m):
        flag = m.group(1)
        content = m.group(2)
        return content if flags.get(flag) else ""
    prev = None
    while prev != text:
        prev = text
        text = COND_RE.sub(_r, text)
    return re.sub(r"\n{3,}", "\n\n", text)


def _render_template(path: Path, flags: dict, placeholders: dict) -> str:
    text = process_conditionals(path.read_text(), flags)
    return substitute(text, placeholders)


def _stage_harness(
    harness: str, out_dir: Path, flags: dict, placeholders: dict,
):
    source = TEMPLATES_DIR / harness
    destination = out_dir / harness
    for template in source.rglob("*"):
        if not template.is_file():
            continue
        staged = destination / template.relative_to(source)
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_text(_render_template(template, flags, placeholders))


def stage_claude(
    out_dir: Path, flags: dict, placeholders: dict, groups: list,
):
    """
    Stage Claude settings and permission definitions.
    """
    values = dict(placeholders)
    matcher_tools = ["Bash", "Write", "Edit"]
    if flags.get("OREAD"):
        matcher_tools.append("Read")
    values["ALLOW_RULES"] = render_rule_array(
        groups, flags, values, exclude_tools=set(matcher_tools),
    )
    values["PERMIT_MATCHER"] = "|".join(matcher_tools)
    bin_dir = values.get("BIN_DIR", str(Path.home() / "bin"))
    executable = _executable(bin_dir, "owrap")
    values["PERMIT_COMMAND"] = f"{executable} p"
    values["CTX_COMMAND"] = f"{executable} ctx-hook"
    _stage_harness("claude", out_dir, flags, values)


def stage_codex(
    out_dir: Path, flags: dict, placeholders: dict, workspace_name: str,
):
    """
    Stage Codex hooks and permission definitions.
    """
    values = dict(placeholders)
    bin_dir = values.get("BIN_DIR", str(Path.home() / "bin"))
    executable = _executable(bin_dir, "owrap")
    values["PERMIT_COMMAND"] = (
        f"{executable} p --workspace {shlex.quote(workspace_name)}"
    )
    values["CTX_COMMAND"] = f"{executable} ctx-hook"
    _stage_harness("codex", out_dir, flags, values)


def resolve_flags(config: dict) -> dict:
    """
    Build the boolean flag map for conditional template blocks.
    """
    oread = bool(config.get("runner_use_oread", True))
    runner_enabled = bool(config.get("owrap_runner_enabled", True))
    context_manager_enabled = bool(
        config.get("owrap_context_manager_enabled", True),
    )
    return {
        "OREAD": oread,
        "NO_OREAD": not oread,
        "RUNNER_ALLOW_ALL": bool(config.get("runner_allow_all", False)),
        "RUNNER_ENABLED": runner_enabled,
        "RUNNER_DISABLED": not runner_enabled,
        "CONTEXT_MANAGER_ENABLED": context_manager_enabled,
        "CONTEXT_MANAGER_DISABLED": not context_manager_enabled,
    }


def _group_active(group: dict, flags: dict) -> bool:
    cond = group.get("condition")
    return flags.get(cond, False) if cond else True


def load_permission_groups(harness: str) -> list:
    """
    Load a harness's permission groups.
    """
    path = TEMPLATES_DIR / harness / "allow.json"
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
    """
    Merge content into dest_path wrapped in owrap markers.

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
    Stage workspace templates and permission hooks, then merge agent files.

    Returns the staged directory.
    """
    _migrate_staged_cache()
    config = get_workspace_config(workspace_name)
    placeholders = resolve_placeholders(config, workspace_name)
    flags = resolve_flags(config)
    workspace_value = config.get("workspace")
    workspace = Path(workspace_value) if workspace_value else None
    docs_value = config.get("docs_root")
    if not docs_value and workspace:
        docs_value = str(workspace / "docs" / "research")
    docs_root = Path(docs_value) if docs_value else None
    instruction_path = (
        _migrate_instructions(docs_root, workspace) if docs_root else None
    )
    instructions = read_instruction_sections(instruction_path) if (
        instruction_path
    ) else {name: "" for name in INSTRUCTION_SECTIONS}

    allow_groups = load_permission_groups("claude")
    codex_groups = load_permission_groups("codex")
    bin_dir = placeholders.get("BIN_DIR", str(Path.home() / "bin"))

    out_dir = staged_dir(workspace_name)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for tpl in TEMPLATES_DIR.rglob("*"):
        if not tpl.is_file():
            continue
        relative = tpl.relative_to(TEMPLATES_DIR)
        if relative.parts[0] in HARNESS_FILES:
            continue
        staged = out_dir / relative
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_text(_render_template(tpl, flags, placeholders))

    _add_workspace_instructions(out_dir / "planner.md", instructions["Planner"])
    _add_workspace_instructions(out_dir / "executor.md", instructions["Executor"])
    _add_workspace_instructions(out_dir / "self.md", instructions["Self"])

    stage_claude(out_dir, flags, placeholders, allow_groups)
    stage_codex(out_dir, flags, placeholders, workspace_name)

    orun_cmd = _tilde_relative(str(Path(bin_dir).expanduser() / "orun"))
    for harness, groups in (("claude", allow_groups), ("codex", codex_groups)):
        permit_rules = [
            substitute(rule, placeholders)
            for group in groups if _group_active(group, flags)
            for rule in group.get("rules", [])
        ]
        suffix = "_codex_permit.json" if harness == "codex" else "_permit.json"
        permit_path = CONFIGS_DIR / f"{workspace_name}{suffix}"
        permit_data = {
            "orun_cmd": orun_cmd,
            "rules": permit_rules,
            "bypass_all": bool(config.get("permit_bypass_all", False)),
        }
        permit_path.write_text(json.dumps(permit_data, indent=2))

    if workspace:
        role_files = resolve_role_files(config)
        planner_staged = out_dir / "planner.md"
        executor_staged = out_dir / "executor.md"
        for role, staged_file in (
            ("planner", planner_staged),
            ("executor", executor_staged),
        ):
            if not staged_file.exists():
                continue
            for filename in ROLE_FILE_NAMES:
                destination = workspace / filename
                if filename in role_files[role]:
                    merge_into_workspace_file(
                        destination, staged_file.read_text(), role,
                    )
                else:
                    _strip_marker_block(destination, role)

    return out_dir


def _migrate_staged_cache() -> None:
    legacy_root = OWRAP_HOME / "staged"
    current_root = staged_dir("_workspace").parent
    if legacy_root == current_root or not legacy_root.is_dir():
        return
    current_root.mkdir(parents=True, exist_ok=True)
    for source in legacy_root.iterdir():
        target = current_root / source.name
        if target.exists():
            if source.is_dir():
                shutil.rmtree(source)
            else:
                source.unlink()
            continue
        shutil.move(str(source), str(target))
    legacy_root.rmdir()
