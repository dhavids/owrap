import json
import sys
from pathlib import Path

from ..utils.paths import OWRAP_ROOT, CONFIGS_DIR, DOCS_DIR, get_self_path


class SetupRunner:
    """Configure owrap for a research project. Does not inherit from BaseRunner — no manager/server needed."""

    def run(self, project_root=None, research_folder=None, update=False):
        if update:
            return self._run_update()
        return self._run_setup(project_root, research_folder)

    def _run_update(self):
        from ..utils.paths import _read_config
        config_path = CONFIGS_DIR / "owrap.json"
        if not config_path.exists():
            print("Error: no config found. Run `owrap setup <project_root>` first.")
            sys.exit(1)
        config = _read_config()

        project_root_path = Path(config.get("project_root", ""))
        research_folder_path = Path(config.get("research_root", str(project_root_path)))
        oread_always = config.get("oread_always", True)

        print("\n=== owrap setup --update ===\n")
        print(f"  project_root:  {project_root_path}")
        print(f"  research_root: {research_folder_path}")
        print(f"  oread_always:  {oread_always}")
        print()

        for tpl_name, apply_fn in (
            ("settings.json", self._apply_settings),
            ("CLAUDE.md",     self._apply_claude_md),
            ("AGENTS.md",     self._apply_agents_md),
            ("self.md",       self._apply_self_md),
        ):
            tpl_path = OWRAP_ROOT / "templates" / tpl_name
            if tpl_path.exists():
                apply_fn(tpl_path, oread_always)

        import os as _os
        rel_owrap_docs = _os.path.relpath(DOCS_DIR, project_root_path)
        _tpl_settings = OWRAP_ROOT / "templates" / "settings.json"
        print()
        print("FILES — planner: update each project file from template:\n")
        for _fname in ("settings.json", "settings.local.json"):
            _dest = project_root_path / ".claude" / _fname
            _status = "EXISTS" if _dest.exists() else "MISSING"
            print(f"  .claude/{_fname:<20} {_status}")
            print(f"                 template:  {_tpl_settings}")
            print(f"                 project:   {_dest}")
            if _dest.exists():
                if oread_always:
                    print(f"                 action:    remove 'Read' from allow; add Grep, Bash(grep *), Bash(ls *), Bash(cat *) to deny")
                else:
                    print(f"                 action:    add 'Read' to allow; remove Grep, Bash(grep *), Bash(ls *), Bash(cat *) from deny")
            else:
                print(f"                 action:    copy template to project file; replace <project_root>, <research_root>, <owrap_docs> placeholders")
        print()
        print("  (doc files — merge missing sections only, leave existing content unchanged)\n")
        for _label, _dest, _tpl in (
            ("CLAUDE.md", project_root_path / "CLAUDE.md",  "CLAUDE.md"),
            ("AGENTS.md", project_root_path / "AGENTS.md",  "AGENTS.md"),
            ("self.md",   research_folder_path / "self.md", "self.md"),
        ):
            _tpl_path = OWRAP_ROOT / "templates" / _tpl
            _status = "EXISTS" if _dest.exists() else "MISSING"
            print(f"  {_label:<14} {_status}")
            print(f"                 template:  {_tpl_path}")
            print(f"                 project:   {_dest}")
            if _dest.exists():
                print(f"                 action:    merge sections in template not present in project file; leave existing content unchanged")
            else:
                print(f"                 action:    copy template to project file and fill in project-specific values")
        print()
        print("SETTINGS — placeholder values for this installation:")
        print(f"    <project_root>   →  {project_root_path}")
        print(f"    <research_root>  →  {research_folder_path}")
        print(f"    <owrap_docs>     →  {rel_owrap_docs}")
        sys.exit(0)

    def _apply_settings(self, settings_path: Path, oread_always: bool):
        with open(settings_path) as f:
            settings = json.load(f)
        perms = settings.setdefault("permissions", {})
        allow = perms.setdefault("allow", [])
        deny = perms.setdefault("deny", [])

        READ_DENY = ["Grep", "Bash(grep *)", "Bash(ls *)", "Bash(cat *)"]
        READ_ALLOW = "Read"

        changed = False
        if oread_always:
            for rule in READ_DENY:
                if rule not in deny:
                    deny.append(rule)
                    changed = True
            if READ_ALLOW in allow:
                allow.remove(READ_ALLOW)
                changed = True
        else:
            for rule in READ_DENY:
                if rule in deny:
                    deny.remove(rule)
                    changed = True
            if READ_ALLOW not in allow:
                allow.insert(0, READ_ALLOW)
                changed = True

        if changed:
            with open(settings_path, "w") as f:
                json.dump(settings, f, indent=2)
            print(f"  updated: .claude/{settings_path.name}")

    def _apply_sentinel(self, path: Path, deny_line: str, allow_line: str, oread_always: bool):
        text = path.read_text()
        target = deny_line if oread_always else allow_line
        current = allow_line if oread_always else deny_line
        if target in text:
            pass
        elif current in text:
            path.write_text(text.replace(current, target))
            print(f"  updated: {path.name}  (oread_always={oread_always})")
        else:
            print(f"  WARNING: {path.name} sentinel not found — needs manual update")

    def _apply_claude_md(self, claude_path: Path, oread_always: bool):
        DENY_LINE = "**Direct `cat`, `ls`, `grep` are denied by permissions.** Always use `~/bin/oread` equivalents above."
        ALLOW_LINE = "**Direct `Read`, `cat`, `ls`, `grep` are allowed** — `~/bin/oread` recommended for large files and directories (auto-summarises, grepping)."
        self._apply_sentinel(claude_path, DENY_LINE, ALLOW_LINE, oread_always)
        DENY_LINE2 = "The Read, Edit, Write, and Bash tools will be denied by permissions."
        ALLOW_LINE2 = "The Edit, Write, and Bash tools will be denied by permissions. Read is permitted."
        self._apply_sentinel(claude_path, DENY_LINE2, ALLOW_LINE2, oread_always)

    def _apply_agents_md(self, agents_path: Path, oread_always: bool):
        DENY_LINE = "The Read, Edit, Write, and Bash tools will be denied by permissions."
        ALLOW_LINE = "The Edit, Write, and Bash tools will be denied by permissions. Read is permitted."
        self._apply_sentinel(agents_path, DENY_LINE, ALLOW_LINE, oread_always)

    def _apply_self_md(self, self_path: Path, oread_always: bool):
        DENY_LINE = "Direct `cat`, `ls`, and `grep` bash commands are denied by permissions."
        ALLOW_LINE = "Direct `cat`, `ls`, `grep`, and Read are allowed — oread recommended for large files and directories."
        self._apply_sentinel(self_path, DENY_LINE, ALLOW_LINE, oread_always)

    def _run_setup(self, project_root=None, research_folder=None):
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

        config = {}
        config_path = CONFIGS_DIR / "owrap.json"
        if config_path.exists():
            with open(config_path) as f:
                config = json.load(f)

        resolved_project_root = config.get("project_root")
        resolved_research_root = config.get("research_root")

        def _resolve_dir(stored):
            if stored:
                p = Path(stored)
                if p.is_dir():
                    return p
                ph = Path.home() / stored
                if ph.is_dir():
                    return ph
            return Path.home()

        project_root_path = _resolve_dir(resolved_project_root)
        research_folder_path = _resolve_dir(resolved_research_root) if resolved_research_root else project_root_path

        claude_path = project_root_path / "CLAUDE.md" if (project_root_path / "CLAUDE.md").exists() else None
        agents_path = project_root_path / "AGENTS.md" if (project_root_path / "AGENTS.md").exists() else None

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
