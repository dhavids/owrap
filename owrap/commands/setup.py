import json
import sys
from pathlib import Path

from ..staging import resolve_role_files, stage_all
from ..utils.checkout import is_development
from ..utils.paths import (
    BASE_CONFIG_FILE, CONFIGS_DIR, FALLBACK_DIR, OWRAP_HOME, OWRAP_ROOT,
    project_config_path,
)
from ..utils.dispatch.model_catalog import discover_free_model


def _read_base() -> dict:
    if BASE_CONFIG_FILE.exists():
        with open(BASE_CONFIG_FILE) as f:
            return json.load(f)
    return {}


def _write_base(data: dict):
    CONFIGS_DIR.mkdir(parents=True, exist_ok=True)
    with open(BASE_CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=2)


def _check_dev_paths(
    workspace: Path, docs_root: Path, config_path: Path,
) -> None:
    """
    Restrict development setup writes to the development files directory.
    """
    if not is_development(OWRAP_ROOT):
        return
    dev_files = (OWRAP_ROOT / "files").resolve()
    destinations = (
        workspace, docs_root, config_path, BASE_CONFIG_FILE,
        CONFIGS_DIR, FALLBACK_DIR, OWRAP_HOME,
    )
    if all(path.resolve().is_relative_to(dev_files) for path in destinations):
        return
    print(f"Error: development setup may write only under {dev_files}.")
    sys.exit(1)


class SetupRunner:
    """
    Create a workspace config and stage its templates.
    """

    def run(self, path=None, project_name=None, workspace=None, docs_root=None,
            allow_all=None, oread=None, planners=None, executors=None):
        """
        Configure an existing workspace and install its agent reference files.
        """
        if path:
            if workspace:
                print("Error: use either <path> or --workspace, not both.")
                sys.exit(1)
            ws = Path(path).expanduser().resolve()
            if not ws.is_dir():
                print(f"Error: workspace path '{ws}' is not a directory.")
                sys.exit(1)
            workspace = str(ws)
            if project_name is None:
                project_name = ws.name
        elif project_name and workspace:
            ws = Path(workspace).expanduser().resolve()
            if not ws.is_dir():
                print(f"Error: workspace '{ws}' is not a directory.")
                sys.exit(1)
            workspace = str(ws)
        else:
            print("Error: positional <path> required, or --name <n> --workspace <path>.")
            sys.exit(1)

        record_root = (
            Path(docs_root).expanduser().resolve()
            if docs_root else ws / "docs" / "research"
        )
        cfg_path = project_config_path(project_name)
        cfg = {}
        if cfg_path.exists():
            with open(cfg_path) as f:
                cfg = json.load(f)
        configured_root = cfg.get("docs_root") or cfg.get("research_root")
        if not docs_root and configured_root:
            record_root = Path(configured_root).expanduser().resolve()
        _check_dev_paths(ws, record_root, cfg_path)

        CONFIGS_DIR.mkdir(parents=True, exist_ok=True)
        cfg["workspace"] = workspace
        cfg["docs_root"] = str(record_root)
        cfg.pop("research_root", None)
        if planners is not None or executors is not None:
            role_harnesses = dict(cfg.get("role_harnesses") or {})
            for role, selected in (("planner", planners), ("executor", executors)):
                if selected is not None:
                    role_harnesses[role] = list(dict.fromkeys(selected))
            resolve_role_files({
                "role_harnesses": role_harnesses,
                "role_files": cfg.get("role_files"),
            })
            cfg["role_harnesses"] = role_harnesses
        if allow_all is not None:
            cfg["runner_allow_all"] = allow_all
        else:
            cfg.setdefault("runner_allow_all", False)
        if oread is not None:
            cfg["runner_use_oread"] = oread
        else:
            cfg.setdefault("runner_use_oread", True)
        cfg.setdefault("context_injection_enabled", True)
        cfg.setdefault("permit_bypass_all", False)
        # runner_model has no safe universal default — left for the user to set.
        free_model = discover_free_model()
        if free_model:
            cfg.setdefault("context_manager_model", free_model)
            cfg.setdefault("context_fallback_model", free_model)
            cfg.setdefault("daemon_default_model", free_model)
        with open(cfg_path, "w") as f:
            json.dump(cfg, f, indent=2)

        # Update global base.json with default_workspace if not set
        base = _read_base()
        base.setdefault("default_workspace", project_name)
        base.setdefault("max_servers", 1)
        base.setdefault("use_multiple_servers", False)
        launcher_dir = (
            OWRAP_ROOT / "files" / "bin"
            if is_development(OWRAP_ROOT)
            else Path.home() / "bin"
        )
        if is_development(OWRAP_ROOT):
            base["bin_dir"] = str(launcher_dir)
        else:
            base.setdefault("bin_dir", str(launcher_dir))
        _write_base(base)

        for subdir in ("run/tasks", "run/output", "exec/output", "read/output"):
            (FALLBACK_DIR / subdir).mkdir(parents=True, exist_ok=True)

        staged = stage_all(project_name)

        print("\n=== owrap setup ===\n")
        print(f"  workspace name: {project_name}")
        print(f"  config:         {cfg_path}")
        print(f"  workspace:      {cfg['workspace']}")
        print(f"  docs root:      {cfg['docs_root']}")
        print(f"  staged:         {staged}")
        print()
        role_files = resolve_role_files(cfg)
        for role, filenames in role_files.items():
            print(f"{role} content merged into {', '.join(filenames)}")
        print(
            "Next: start or attach a session, then run `owrap sync` "
            "to install workspace settings and hooks."
        )
        sys.exit(0)
