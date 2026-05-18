import json
import os
from pathlib import Path

OWRAP_ROOT = Path(__file__).resolve().parents[2]
DOCS_DIR = OWRAP_ROOT / "docs"
TEMPLATES_DIR = OWRAP_ROOT / "templates"
CONFIGS_DIR = OWRAP_ROOT / "configs"
CONFIG_FILE = CONFIGS_DIR / "owrap.json"

# Session-scoped paths
SESSION_DIR = Path.home() / ".owrap"

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
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            return json.load(f)
    return {}


def get_plan_path(session_id: str) -> Path:
    """Return session-scoped plan path. session_id is required (always set after owrap start)."""
    return DOCS_DIR / f"plan_{session_id}.md"


def get_self_path() -> Path:
    """Return self.md path: research_root/self.md if configured, else DOCS_DIR/self.md fallback."""
    config = _read_config()
    research_root = config.get("research_root")
    if research_root:
        return Path(research_root) / "self.md"
    return DOCS_DIR / "self.md"


def get_project_root() -> Path:
    """Return project_root if configured, else fall back to research_root parent or DOCS_DIR parent."""
    config = _read_config()
    v = config.get("project_root")
    if v:
        return Path(v)
    v = config.get("research_root")
    if v:
        return Path(v).parent
    return DOCS_DIR.parent


def get_todo_path() -> Path:
    research = os.environ.get("OWRAP_RESEARCH", "")
    config = _read_config()
    research_root = config.get("research_root")
    if research and research_root:
        return Path(research_root) / "projects" / f"{research}.md"
    return DOCS_DIR / "todo.md"
