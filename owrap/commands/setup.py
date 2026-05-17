import json
import sys
from pathlib import Path

from ..utils.paths import OWRAP_ROOT, CONFIGS_DIR, DOCS_DIR, get_self_path


class SetupRunner:
    """Configure owrap for a research project. Does not inherit from BaseRunner — no manager/server needed."""

    def run(self, research_root=None):
        resolved_research_root = None

        if research_root is not None:
            resolved = Path(research_root).resolve()
            if not resolved.is_dir():
                print(f"Error: '{research_root}' is not a valid directory.")
                sys.exit(1)

            config_path = CONFIGS_DIR / "owrap.json"
            if config_path.exists():
                with open(config_path) as f:
                    config = json.load(f)
            else:
                template_path = OWRAP_ROOT / "templates" / "config.json"
                with open(template_path) as f:
                    config = json.load(f)

            config["research_root"] = str(resolved)

            CONFIGS_DIR.mkdir(parents=True, exist_ok=True)
            with open(config_path, "w") as f:
                json.dump(config, f, indent=2)

            resolved_research_root = str(resolved)

        def check_file(filename, search_from):
            current = search_from
            for _ in range(6):
                candidate = current / filename
                if candidate.exists():
                    return candidate
                if current == current.parent:
                    break
                current = current.parent
            return None

        cwd = Path.cwd()
        claude_path = check_file("CLAUDE.md", cwd)
        agents_path = check_file("AGENTS.md", cwd)
        self_path = get_self_path()

        def status_line(filename, found_path, dest_path):
            template_name = OWRAP_ROOT / "templates" / filename
            if found_path is None:
                return f"MISSING: Copy {template_name} to {dest_path} and fill in project-specific values."
            else:
                return f"EXISTS: Read {found_path} and {template_name}. Only update {found_path} if the template has sections or modes not present in the existing file. If the existing file is already more detailed, leave it unchanged."

        config = {}
        config_path = CONFIGS_DIR / "owrap.json"
        if config_path.exists():
            with open(config_path) as f:
                config = json.load(f)
        resolved_research_root = config.get("research_root")
        if resolved_research_root:
            research_root_path = Path(resolved_research_root)
        else:
            research_root_path = cwd

        claude_dest = research_root_path / "CLAUDE.md"
        agents_dest = research_root_path / "AGENTS.md"
        self_dest = get_self_path()

        claude_status = status_line("CLAUDE.md", claude_path, claude_dest)
        agents_status = status_line("AGENTS.md", agents_path, agents_dest)
        self_status = status_line("self.md", self_path if self_path.exists() else None, self_dest)

        print("\n=== owrap setup ===\n")
        if research_root is not None:
            print(f"✓ research_root set to '{Path(research_root).resolve()}' in configs/owrap.json\n")
        print("FILES — check each and act accordingly:\n")
        print(f"  CLAUDE.md     {claude_status}")
        print(f"  AGENTS.md     {agents_status}")
        print(f"  self.md       {self_status}")
        print("\n  EXISTS rule:  Read the existing file and the template side by side.")
        print("                Only add sections or modes that are missing from the existing file.")
        print("                Do not overwrite, reorder, or remove any existing content.")
        print("  MISSING rule: Copy the template to the destination and fill in project-specific")
        print("                values (project name, research topic, paths).")
        print("\nSETTINGS\n")
        print(f"  Copy {OWRAP_ROOT}/templates/settings.json to .claude/settings.json")
        print("  (or .claude/settings.local.json for local-only).")
        print()
        placeholder = resolved_research_root or "<not yet set — run owrap setup <path> first>"
        print(f"  Then replace the two placeholders:")
        print(f"    <research_root>  →  {placeholder}")
        print(f"    <owrap_docs>     →  {DOCS_DIR}")
        print()
        print("  The settings file grants the planner permission to read/edit plan files,")
        print("  project files, and dispatch owrap commands without prompting.")
        print("\nNEXT STEPS\n")
        print("  1. Act on each FILES item above (copy or merge).")
        print("  2. Update settings.json placeholders.")
        print("  3. Run `owrap start <research_name>` to begin your session.")
        print("     If research_name is already set in config, `owrap start` is enough.")

        sys.exit(0)
