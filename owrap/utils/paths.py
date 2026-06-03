import json
import os
from pathlib import Path

OWRAP_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_HOME = Path.home() / ".owrap"
DOCS_DIR = RUNTIME_HOME / "docs"
TEMPLATES_DIR = OWRAP_ROOT / "templates"
CONFIGS_DIR = RUNTIME_HOME / "configs"
BASE_CONFIG_FILE = CONFIGS_DIR / "base.json"

# Session-scoped paths
SESSION_DIR = Path.home() / ".owrap"
RUNNING_DIR = SESSION_DIR / "running"
RECENTLY_DONE_DIR = SESSION_DIR / "recently_done"
SERVERS_DIR = SESSION_DIR / "servers"

# Runtime output paths (all under DOCS_DIR)
RUN_DIR = DOCS_DIR / "run"
TASKS_DIR = RUN_DIR / "tasks"
INPUT_FILE = TASKS_DIR / "input.md"
RUN_OUTPUT_DIR = RUN_DIR / "output"
RUN_LOG = RUN_DIR / "log.md"

EXEC_DIR = DOCS_DIR / "exec"
EXEC_OUTPUT_DIR = EXEC_DIR / "output"
EXEC_LOG = EXEC_DIR / "log.md"

READ_DIR = DOCS_DIR / "read"
READ_OUTPUT_DIR = READ_DIR / "output"
READ_LOG = READ_DIR / "log.md"

STATE_FILE = str(Path.home() / ".owrap" / "manager.json")


def session_log(base_log: Path, session_id: str) -> Path:
    """Return session-scoped log path, or base_log if no session."""
    if session_id:
        return base_log.parent / f"{base_log.stem}_{session_id}{base_log.suffix}"
    return base_log


def session_input(session_id: str) -> Path:
    """Return session-scoped input path, or INPUT_FILE if no session."""
    if session_id:
        return TASKS_DIR / f"input_{session_id}.md"
    return INPUT_FILE


def _read_config() -> dict:
    """Read global base config (~/.owrap/configs/base.json). Returns {} if missing."""
    if BASE_CONFIG_FILE.exists():
        with open(BASE_CONFIG_FILE) as f:
            return json.load(f)
    return {}


def get_workspace_config(workspace_name: str) -> dict:
    """Read workspace-scoped config from ~/.owrap/configs/<workspace_name>.json. Returns {} if missing."""
    if not workspace_name:
        return {}
    p = CONFIGS_DIR / f"{workspace_name}.json"
    if p.exists():
        with open(p) as f:
            return json.load(f)
    return {}


def get_project_config(project_name: str) -> dict:
    """Read per-project config from ~/.owrap/configs/<project_name>.json. Returns {} if missing."""
    if not project_name:
        return {}
    p = CONFIGS_DIR / f"{project_name}.json"
    if p.exists():
        with open(p) as f:
            return json.load(f)
    return {}


def project_config_path(project_name: str):
    return CONFIGS_DIR / f"{project_name}.json"


def staged_dir(project_name: str):
    return RUNTIME_HOME / "staged" / project_name


def get_plan_path(session_id: str) -> Path:
    """Return session-scoped plan path. session_id is required (always set after owrap start)."""
    return DOCS_DIR / f"plan_{session_id}.md"


def get_self_path() -> Path:
    """Return self.md path: research_root/self.md if configured, else DOCS_DIR/self.md fallback."""
    config = _read_config()
    ws_name = config.get("default_workspace", "")
    if ws_name:
        ws_cfg = get_workspace_config(ws_name)
        research_root = ws_cfg.get("research_root")
        if research_root:
            return Path(research_root) / "self.md"
    research_root = config.get("research_root")
    if research_root:
        return Path(research_root) / "self.md"
    return DOCS_DIR / "self.md"


def get_agents_md_path() -> Path | None:
    """Return AGENTS.md path from workspace config, or None if not configured."""
    config = _read_config()
    default_ws = config.get("default_workspace")
    if default_ws:
        ws_config = get_workspace_config(default_ws)
        v = ws_config.get("workspace")
        if v:
            p = Path(v) / "AGENTS.md"
            if p.exists():
                return p
    return None


def get_workspace_path() -> Path:
    """Return workspace from workspace config, else fall back to research_root parent or DOCS_DIR parent."""
    config = _read_config()
    default_ws = config.get("default_workspace")
    if default_ws:
        ws_config = get_workspace_config(default_ws)
        v = ws_config.get("workspace")
        if v:
            return Path(v)
    v = config.get("research_root")
    if v:
        return Path(v).parent
    return DOCS_DIR.parent


def get_todo_path(research: str = None) -> Path:
    if research is None:
        research = os.environ.get("OWRAP_RESEARCH", "")
    config = _read_config()
    ws_name = config.get("default_workspace", "")
    research_root = None
    if ws_name:
        research_root = get_workspace_config(ws_name).get("research_root")
    if not research_root:
        research_root = config.get("research_root")
    if research and research_root:
        return Path(research_root) / "projects" / f"{research}.md"
    return DOCS_DIR / "todo.md"


def server_state_file(port: int) -> Path:
    return SERVERS_DIR / f"{port}.json"


def context_path(session_id: str) -> Path:
    """Return session-scoped context file path."""
    return DOCS_DIR / f"context_{session_id}.md"


def context_lock_path(session_id: str) -> Path:
    """Return session-scoped context lock file path."""
    return DOCS_DIR / f"context_{session_id}.lock"
