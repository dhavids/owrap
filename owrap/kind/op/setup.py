import json
from pathlib import Path

from . import Op
from ...utils.checkout import is_development
from ...utils.dispatch.model_catalog import discover_free_model
from ...utils.paths import (
    BASE_CONFIG_FILE, CONFIGS_DIR, FALLBACK_DIR, OWRAP_HOME, OWRAP_ROOT,
    project_config_path,
)
from ...utils.staging import resolve_role_files, stage_all


class Setup(Op):
    """
    Configure a workspace -- its config file, docs root, and agent
    reference files -- and stage its templates.
    """

    kind = "setup"

    usage = {
        "do": {
            "usage": "<path> | --name <n> --workspace <path> [options]",
            "args": [
                ("path", "workspace directory (derives name from basename)"),
                ("docs_root", "path to project/repository records"),
            ],
            "examples": ["/path/to/workspace"],
        },
    }

    messages = {"do": "{message}"}


    # Public Methods

    def do(
        self, path: str = None, project_name: str = None, workspace: str = None,
        docs_root: str = None, allow_all: bool = None, oread: bool = None,
        planners: list = None, executors: list = None,
    ) -> None:
        workspace, project_name = self._resolve_setup_target(
            path, project_name, workspace,
        )
        record_root, cfg_path, cfg = self._resolve_docs_root(
            workspace, docs_root, project_name,
        )
        self._write_workspace_config(
            cfg, cfg_path, workspace, record_root, allow_all, oread, planners, executors,
        )
        self._write_base_config(project_name)
        for subdir in ("run/tasks", "run/output", "exec/output", "read/output"):
            (FALLBACK_DIR / subdir).mkdir(parents=True, exist_ok=True)
        staged = stage_all(project_name)

        lines = [
            "", "=== owrap setup ===", "",
            f"  workspace name: {project_name}",
            f"  config:         {cfg_path}",
            f"  workspace:      {cfg['workspace']}",
            f"  docs root:      {cfg['docs_root']}",
            f"  staged:         {staged}", "",
        ]
        role_files = resolve_role_files(cfg)
        for role, filenames in role_files.items():
            lines.append(f"{role} content merged into {', '.join(filenames)}")
        lines.append(
            "Next: start or attach a session, then run `owrap sync` to "
            "install workspace settings and hooks."
        )
        self._ok("do", message="\n".join(lines))


    # Private Methods

    def _resolve_setup_target(self, path, project_name, workspace) -> tuple:
        if path:
            if workspace:
                self._fail("use either <path> or --workspace, not both.")
            ws = Path(path).expanduser().resolve()
            if not ws.is_dir():
                self._fail(f"workspace path '{ws}' is not a directory.")
            workspace = str(ws)
            if project_name is None:
                project_name = ws.name
        elif project_name and workspace:
            ws = Path(workspace).expanduser().resolve()
            if not ws.is_dir():
                self._fail(f"workspace '{ws}' is not a directory.")
            workspace = str(ws)
        else:
            self._fail("positional <path> required, or --name <n> --workspace <path>.")
        return workspace, project_name

    def _resolve_docs_root(self, workspace, docs_root, project_name) -> tuple:
        ws = Path(workspace)
        record_root = (
            Path(docs_root).expanduser().resolve() if docs_root
            else ws / "docs" / "research"
        )
        cfg_path = project_config_path(project_name)
        cfg = json.loads(cfg_path.read_text()) if cfg_path.exists() else {}
        configured_root = cfg.get("docs_root") or cfg.get("research_root")
        if not docs_root and configured_root:
            record_root = Path(configured_root).expanduser().resolve()
        self._check_dev_paths(ws, record_root, cfg_path)
        return record_root, cfg_path, cfg

    def _check_dev_paths(
        self, workspace: Path, docs_root: Path, config_path: Path,
    ) -> None:
        if not is_development(OWRAP_ROOT):
            return
        dev_files = (OWRAP_ROOT / "files").resolve()
        destinations = (
            workspace, docs_root, config_path, BASE_CONFIG_FILE,
            CONFIGS_DIR, FALLBACK_DIR, OWRAP_HOME,
        )
        if all(p.resolve().is_relative_to(dev_files) for p in destinations):
            return
        self._fail(f"development setup may write only under {dev_files}.")

    def _write_workspace_config(
        self, cfg, cfg_path, workspace, record_root, allow_all, oread,
        planners, executors,
    ) -> None:
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
                "role_harnesses": role_harnesses, "role_files": cfg.get("role_files"),
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
        free_model = discover_free_model()
        if free_model:
            cfg.setdefault("context_manager_model", free_model)
            cfg.setdefault("context_fallback_model", free_model)
            cfg.setdefault("daemon_default_model", free_model)
        cfg_path.write_text(json.dumps(cfg, indent=2))

    def _write_base_config(self, project_name: str) -> None:
        base = (
            json.loads(BASE_CONFIG_FILE.read_text())
            if BASE_CONFIG_FILE.exists() else {}
        )
        base.setdefault("default_workspace", project_name)
        base.setdefault("max_servers", 1)
        base.setdefault("use_multiple_servers", False)
        launcher_dir = (
            OWRAP_ROOT / "files" / "bin" if is_development(OWRAP_ROOT)
            else Path.home() / "bin"
        )
        if is_development(OWRAP_ROOT):
            base["bin_dir"] = str(launcher_dir)
        else:
            base.setdefault("bin_dir", str(launcher_dir))
        CONFIGS_DIR.mkdir(parents=True, exist_ok=True)
        BASE_CONFIG_FILE.write_text(json.dumps(base, indent=2))
