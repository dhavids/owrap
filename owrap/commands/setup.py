import json
import sys
from pathlib import Path

from ..utils.paths import OWRAP_ROOT, CONFIGS_DIR, DOCS_DIR, get_self_path


class SetupRunner:
    """Configure owrap for a research project. Does not inherit from BaseRunner — no manager/server needed."""

    def run(self, project_root=None, research_folder=None):
        research_folder = research_folder or project_root

        if project_root is not None:
            resolved_project = Path(project_root).resolve()
            if not resolved_project.is_dir():
                print(f"Error: '{project_root}' is not a valid directory.")
                sys.exit(1)
            resolved_research = Path(research_folder).resolve()
            if not resolved_research.is_dir():
                print(f"Error: '{research_folder}' is not a valid directory.")
                sys.exit(1)

            config_path = CONFIGS_DIR / "owrap.json"
            if config_path.exists():
                with open(config_path) as f:
                    config = json.load(f)
            else:
                template_path = OWRAP_ROOT / "templates" / "config.json"
                with open(template_path) as f:
                    config = json.load(f)

            config["project_root"] = str(resolved_project)
            config["research_root"] = str(resolved_research)

            CONFIGS_DIR.mkdir(parents=True, exist_ok=True)
            with open(config_path, "w") as f:
                json.dump(config, f, indent=2)

        def _find_upward(filename, search_from):
            current = search_from
            for _ in range(6):
                candidate = current / filename
                if candidate.exists():
                    return candidate
                if current == current.parent:
                    break
                current = current.parent
            return None

        config = {}
        config_path = CONFIGS_DIR / "owrap.json"
        if config_path.exists():
            with open(config_path) as f:
                config = json.load(f)

        resolved_project_root = config.get("project_root")
        resolved_research_root = config.get("research_root")

        project_root_path = Path(resolved_project_root) if resolved_project_root else Path.cwd()
        research_folder_path = Path(resolved_research_root) if resolved_research_root else project_root_path

        if resolved_project_root:
            claude_path = project_root_path / "CLAUDE.md" if (project_root_path / "CLAUDE.md").exists() else None
            agents_path = project_root_path / "AGENTS.md" if (project_root_path / "AGENTS.md").exists() else None
        else:
            cwd = Path.cwd()
            claude_path = _find_upward("CLAUDE.md", cwd)
            agents_path = _find_upward("AGENTS.md", cwd)

        self_path = research_folder_path / "self.md"

        claude_dest = project_root_path / "CLAUDE.md"
        agents_dest = project_root_path / "AGENTS.md"
        self_dest = research_folder_path / "self.md"

        def status_line(filename, found_path, dest_path):
            template_name = OWRAP_ROOT / "templates" / filename
            if found_path is None:
                return f"MISSING: Copy {template_name} to {dest_path} and fill in project-specific values."
            else:
                return f"EXISTS: Read {found_path} and {template_name}. Only update {found_path} if the template has sections or modes not present in the existing file. If the existing file is already more detailed, leave it unchanged."

        claude_status = status_line("CLAUDE.md", claude_path, claude_dest)
        agents_status = status_line("AGENTS.md", agents_path, agents_dest)
        self_status = status_line("self.md", self_path if self_path.exists() else None, self_dest)

        print("\n=== owrap setup ===\n")
        if project_root is not None:
            print(f"✓ project_root set to '{resolved_project}' in configs/owrap.json")
            if research_folder != project_root:
                print(f"✓ research_root set to '{resolved_research}' in configs/owrap.json")
            print()
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
        print(f"  Copy {OWRAP_ROOT}/templates/settings.json to BOTH {project_root_path}/.claude/settings.json AND {project_root_path}/.claude/settings.local.json.")
        print()
        import os
        rel_owrap_docs = os.path.relpath(DOCS_DIR, project_root_path)
        print(f"  Then replace the placeholders (use paths RELATIVE to project_root for Edit/Read rules):")
        print(f"    <project_root>   →  {project_root_path}  (absolute — used in additionalDirectories only)")
        print(f"    <research_root>  →  {os.path.relpath(research_folder_path, project_root_path)}")
        print(f"    <owrap_docs>     →  {rel_owrap_docs}")
        print()
        print("  The settings file grants the planner permission to read/edit plan files,")
        print("  project files, and dispatch owrap commands without prompting.")
        print("\nNEXT STEPS\n")
        print("  1. Act on each FILES item above (copy or merge).")
        print("  2. Update settings.json placeholders.")
        print("  3. Run `~/bin/owrap start <research_name>` to begin your session.")
        print("     If research_name is already set in config, `~/bin/owrap start` is enough.")

        sys.exit(0)
