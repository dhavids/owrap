import json
import sys
from pathlib import Path

from ..staging import stage_all
from ..utils.paths import CONFIGS_DIR, DOCS_DIR, BASE_CONFIG_FILE, project_config_path


def _read_base() -> dict:
    if BASE_CONFIG_FILE.exists():
        with open(BASE_CONFIG_FILE) as f:
            return json.load(f)
    return {}


def _write_base(data: dict):
    CONFIGS_DIR.mkdir(parents=True, exist_ok=True)
    with open(BASE_CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=2)


class SetupRunner:
    """Create per-workspace config + stage templates. Does not run orun; planner does."""

    def run(self, path=None, project_name=None, workspace=None, research_root=None,
            allow_all=None, oread=None):
        # Derive workspace name and path from positional arg
        if path:
            ws = Path(path).expanduser().resolve()
            if not ws.is_dir():
                print(f"Error: workspace path '{ws}' is not a directory.")
                sys.exit(1)
            name = ws.name
            workspace = str(ws)
            if project_name is None:
                project_name = name
        elif project_name and workspace:
            ws = Path(workspace).expanduser().resolve()
            if not ws.is_dir():
                print(f"Error: workspace '{ws}' is not a directory.")
                sys.exit(1)
            workspace = str(ws)
        else:
            print("Error: positional <path> required, or --name <n> --workspace <path>.")
            sys.exit(1)

        cfg_path = project_config_path(project_name)
        CONFIGS_DIR.mkdir(parents=True, exist_ok=True)
        cfg = {}
        if cfg_path.exists():
            with open(cfg_path) as f:
                cfg = json.load(f)
        cfg["workspace"] = workspace
        if research_root:
            cfg["research_root"] = str(Path(research_root).expanduser().resolve())
        else:
            cfg.setdefault("research_root", str(ws / "docs" / "research"))
        cfg.setdefault("allow_all", False if allow_all is None else allow_all)
        cfg.setdefault("oread", True if oread is None else oread)
        cfg.setdefault("context_enabled", True)
        with open(cfg_path, "w") as f:
            json.dump(cfg, f, indent=2)

        # Update global base.json with default_workspace if not set
        base = _read_base()
        base.setdefault("default_workspace", project_name)
        base.setdefault("max_servers", 1)
        base.setdefault("use_multiple_servers", False)
        base.setdefault("bin_dir", str(Path.home() / "bin"))
        _write_base(base)

        for subdir in ("run/tasks", "run/output", "exec/output", "read/output"):
            (DOCS_DIR / subdir).mkdir(parents=True, exist_ok=True)

        staged = stage_all(project_name)

        # Delete standalone planner.md and executor.md (now merged into
        # CLAUDE.md/AGENTS.md)
        ws = Path(workspace)
        for stale in ("planner.md", "executor.md"):
            (ws / stale).unlink(missing_ok=True)

        print("\n=== owrap setup ===\n")
        print(f"  workspace name: {project_name}")
        print(f"  config:         {cfg_path}")
        print(f"  workspace:      {cfg['workspace']}")
        print(f"  research_root:  {cfg['research_root']}")
        print(f"  staged:         {staged}")
        print()
        print(
            "planner content merged into CLAUDE.md; "
            "executor content merged into AGENTS.md"
        )
        print(
            "Next: run `~/bin/owrap sync` (via orun) to apply "
            "staged templates to project files."
        )
        sys.exit(0)
