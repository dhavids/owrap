import json
import os
from pathlib import Path

from .checkout import is_development

OWRAP_ROOT = Path(__file__).resolve().parents[2]

OWRAP_HOME_POINTER_FILE = Path.home() / ".owrap_home"


_env_home = os.environ.get("OWRAP_HOME", "").strip()
if is_development(OWRAP_ROOT):
    dev_files = (OWRAP_ROOT / "files").resolve()
    if not dev_files.is_relative_to(OWRAP_ROOT):
        raise RuntimeError("Development files directory leaves the checkout")
    OWRAP_HOME = Path(_env_home).expanduser() if _env_home else dev_files / "state"
    OWRAP_HOME = OWRAP_HOME.resolve()
    if not OWRAP_HOME.is_relative_to(dev_files):
        raise RuntimeError(f"Development OWRAP_HOME must be under {dev_files}")
elif _env_home:
    OWRAP_HOME = Path(_env_home).expanduser()
elif OWRAP_HOME_POINTER_FILE.exists():
    try:
        _ptr = OWRAP_HOME_POINTER_FILE.read_text().strip()
        OWRAP_HOME = Path(_ptr).expanduser() if _ptr else Path.home() / ".owrap"
    except OSError:
        OWRAP_HOME = Path.home() / ".owrap"
else:
    OWRAP_HOME = Path.home() / ".owrap"
del _env_home
RUNTIME_HOME = OWRAP_HOME
RUNTIME_DIR = RUNTIME_HOME / "runtime"
RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
# Read-only compatibility root until legacy runtime files are migrated.
DOCS_DIR = RUNTIME_HOME / "docs"
SESSIONS_DIR = RUNTIME_HOME / "sessions"
LEGACY_SESSIONS_DIR = DOCS_DIR / "sessions"
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
LOCKS_DIR = RUNTIME_HOME / "locks"
LOCKS_DIR.mkdir(parents=True, exist_ok=True)
BACKUPS_DIR = RUNTIME_HOME / "backups"
BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
TEMPLATES_DIR = OWRAP_ROOT / "templates"
CONFIGS_DIR = RUNTIME_HOME / "configs"
BASE_CONFIG_FILE = CONFIGS_DIR / "base.json"


# Session-scoped paths
SESSION_DIR = OWRAP_HOME
RUNNING_DIR = SESSION_DIR / "running"
RECENTLY_DONE_DIR = SESSION_DIR / "recently_done"
SERVERS_DIR = SESSION_DIR / "servers"
TRASH_DIR = OWRAP_HOME / ".trash"


# Unattached work uses the fallback session tree.
FALLBACK_DIR = SESSIONS_DIR / "f"
RUN_DIR = FALLBACK_DIR / "run"
TASKS_DIR = RUN_DIR / "tasks"
INPUT_FILE = TASKS_DIR / "input.md"
RUN_LOG = RUN_DIR / "log.md"

SERVER_LOGS_DIR = RUNTIME_HOME / "logs"
RUNTIME_LOG = RUNTIME_DIR / "runtime.log"
RUNTIME_LOG_MAX_BYTES = 5 * 1024 * 1024
RUNTIME_LOG_GENERATIONS = 3

SERVER_LOGS_DIR.mkdir(parents=True, exist_ok=True)

EXEC_LOG = FALLBACK_DIR / "exec" / "log.md"

FALLBACK_EXEC_DIR = FALLBACK_DIR / "exec"
FALLBACK_EXEC_DIR.mkdir(parents=True, exist_ok=True)
FALLBACK_PLAN = FALLBACK_EXEC_DIR / "plan.md"

FALLBACK_TASK_DIR = FALLBACK_DIR / "task"
FALLBACK_TASK_DIR.mkdir(parents=True, exist_ok=True)
FALLBACK_TASK = FALLBACK_TASK_DIR / "task.md"
FALLBACK_EXEC_OUTPUT = FALLBACK_EXEC_DIR / "output.log"
FALLBACK_EXEC_LOG = FALLBACK_EXEC_DIR / "log.md"
FALLBACK_TASK_OUTPUT = FALLBACK_TASK_DIR / "output.log"
FALLBACK_TASK_LOG = FALLBACK_TASK_DIR / "log.md"
FALLBACK_EXEC_STATUS = FALLBACK_EXEC_DIR / "status.json"
FALLBACK_TASK_STATUS = FALLBACK_TASK_DIR / "status.json"

READ_LOG = FALLBACK_DIR / "read" / "log.md"

STATE_FILE = str(RUNTIME_DIR / "manager.json")
POOL_FILE = RUNTIME_DIR / "pool.json"
POOL_LOCK_FILE = RUNTIME_DIR / "pool.lock"
DAEMON_PID_FILE = RUNTIME_DIR / "daemon.pid"
DAEMON_STATE_FILE = RUNTIME_DIR / "daemon.state"
DAEMON_LOCK_FILE = RUNTIME_DIR / "daemon.lock"
STATS_FILE = RUNTIME_DIR / "stats.json"
OPENCODE_STATUS_FILE = RUNTIME_DIR / "opencode_status.json"

_config_cache: dict | None = None
_config_cache_stat: tuple | None = None


def _resolve_owrap_home() -> Path:
    """
    Resolve the OWRAP_HOME directory: $OWRAP_HOME env var >
    ~/.owrap_home pointer file > ~/.owrap default.

    The pointer file lives at a fixed location outside the relocatable
    directory itself, and is what `owrap update-home` rewrites when
    relocating.
    """
    if is_development(OWRAP_ROOT):
        return OWRAP_HOME
    env_val = os.environ.get("OWRAP_HOME", "").strip()
    if env_val:
        return Path(env_val).expanduser()
    if OWRAP_HOME_POINTER_FILE.exists():
        try:
            pointer_val = OWRAP_HOME_POINTER_FILE.read_text().strip()
            if pointer_val:
                return Path(pointer_val).expanduser()
        except OSError:
            pass
    return Path.home() / ".owrap"


def session_dir(session_id: str) -> Path:
    current = SESSIONS_DIR / session_id
    legacy = LEGACY_SESSIONS_DIR / session_id
    return legacy if not current.exists() and legacy.exists() else current


def session_ctx_counters_path(session_id: str, harness_id: str) -> Path:
    current = (
        session_dir(session_id) / "ctx" / "windows" / harness_id
        / "counters.json"
    )
    name = f"{session_id}.{harness_id}.counters.json"
    flat = SESSIONS_DIR / name
    legacy = LEGACY_SESSIONS_DIR / name
    if not current.exists() and flat.exists():
        return flat
    return legacy if not current.exists() and legacy.exists() else current


def session_log(base_log: Path, session_id: str) -> Path:
    """
    Return session-scoped log path, or base_log if no session.
    """
    if session_id:
        return session_dir(session_id) / base_log.parent.name / base_log.name
    return base_log


def session_input(session_id: str) -> Path:
    """
    Return session-scoped input path, or INPUT_FILE if no session.
    """
    if session_id:
        return session_dir(session_id) / "run" / "input.md"
    return INPUT_FILE


def session_exec_output_path(session_id: str) -> Path:
    return session_dir(session_id) / "exec" / "output.log"


def session_ctx_root(session_id: str) -> Path:
    """
    Return the session's context workspace root.
    """
    return session_dir(session_id) / "ctx"


def session_ctx_dir(session_id: str, ccsid: str) -> Path:
    """
    Return the per-window context-manager state directory.

    Existing per-window directories remain readable after the layout change.
    """
    root = session_ctx_root(session_id)
    current = root / "windows" / ccsid
    legacy = root / ccsid
    if legacy.exists() and not current.exists():
        return legacy
    return current


def session_ctx_jobs_dir(session_id: str) -> Path:
    """
    Return the session-wide context job directory.
    """
    return session_ctx_root(session_id) / "jobs"


def session_ctx_input_path(session_id: str, ccsid: str) -> Path:
    return session_ctx_dir(session_id, ccsid) / "input.md"


def session_ctx_transcript_path(session_id: str, ccsid: str) -> Path:
    return session_ctx_dir(session_id, ccsid) / "transcript.txt"


def session_ctx_touched_path(session_id: str, ccsid: str) -> Path:
    """
    Per-window pending-paths file (item 14): paths the planner explicitly
    reported touching, queued here until the next context-manager dispatch
    picks them up.
    """
    return session_ctx_dir(session_id, ccsid) / "touched.json"


def session_tasks_dir(session_id: str) -> Path:
    return session_dir(session_id) / "run" / "tasks"


def session_msg_output_dir(session_id: str) -> Path:
    return session_dir(session_id) / "run" / "output" / "msg"


def session_task_output_dir(session_id: str) -> Path:
    return session_dir(session_id) / "run" / "output" / "tasks"


def session_agents_dir(session_id: str) -> Path:
    return session_dir(session_id) / "agents"


def session_agent_log_path(session_id: str) -> Path:
    return session_agents_dir(session_id) / "output.log"


def session_agent_full_log_dir(session_id: str) -> Path:
    return session_agents_dir(session_id) / "output"


def _read_config() -> dict:
    """
    Read base config merged with the default workspace config.

    Base keys are overridden by workspace keys.
    """
    global _config_cache, _config_cache_stat
    if BASE_CONFIG_FILE.exists():
        st = os.stat(BASE_CONFIG_FILE)
        stat_tuple = (st.st_mtime, st.st_size)
        if _config_cache is not None and _config_cache_stat == stat_tuple:
            return _config_cache
        with open(BASE_CONFIG_FILE) as f:
            base = json.load(f)
        ws_name = base.get("default_workspace", "")
        if ws_name:
            ws_cfg = get_workspace_config(ws_name)
            merged = {**base, **ws_cfg}
        else:
            merged = base
        _config_cache = merged
        _config_cache_stat = stat_tuple
        return _config_cache
    return {}


def get_workspace_config(workspace_name: str) -> dict:
    """
    Read workspace-scoped config from
    ~/.owrap/configs/<workspace_name>.json.

    Returns {} if missing.
    """
    if not workspace_name:
        return {}
    p = CONFIGS_DIR / f"{workspace_name}.json"
    if p.exists():
        with open(p) as f:
            return json.load(f)
    return {}


def get_project_config(project_name: str) -> dict:
    """
    Read per-project config from ~/.owrap/configs/<project_name>.json.

    Returns {} if missing.
    """
    if not project_name:
        return {}
    p = CONFIGS_DIR / f"{project_name}.json"
    if p.exists():
        with open(p) as f:
            return json.load(f)
    return {}


def project_config_path(project_name: str):
    return CONFIGS_DIR / f"{project_name}.json"


def get_dispatch_model(
    config: dict,
    override: str | None = None,
    default_to_fast: bool = False,
) -> str | None:
    """
    Resolve the model to pass to `opencode run` for an owrap dispatch.

    Resolution order:
    1. override argument (e.g. CLI --model)
    2. config["runner_model"]
    3. config["fast_model"] if default_to_fast is True
    4. None (let opencode use its default)
    """
    if override:
        return override
    if config.get("runner_model"):
        return config["runner_model"]
    if default_to_fast and config.get("fast_model"):
        return config["fast_model"]
    return None


def get_model_chain(config: dict, key: str = "context_manager_model") -> list:
    """
    Ordered, deduplicated list of models to try for a background
    context-manager task: config[key] -> config["runner_model"] ->
    config["context_fallback_model"]. The last is the named, already-
    proven free-tier model configured as `base.json`'s default — a
    config value, never hardcoded here, so a user can repoint it. Can be
    empty if none of these are configured.
    """
    candidates = [
        config.get(key), config.get("runner_model"),
        config.get("context_fallback_model"),
    ]
    seen = set()
    chain = []
    for m in candidates:
        if m and m not in seen:
            seen.add(m)
            chain.append(m)
    return chain


def get_maintenance_model(
    config: dict, key: str = "context_manager_model",
) -> str | None:
    """
    Resolve the single best model for a background context-manager task —
    the first entry of `get_model_chain`, or None if nothing is configured.
    """
    chain = get_model_chain(config, key)
    return chain[0] if chain else None


def staged_dir(project_name: str):
    return RUNTIME_DIR / "staged" / project_name


def get_plan_path(session_id: str) -> Path:
    """
    Return session-scoped plan path.

    session_id is required (always set after owrap start).
    """
    return session_dir(session_id) / "exec" / "plan.md"


def get_self_path() -> Path:
    """
    Return the staged self.md for the configured workspace.
    """
    config = _read_config()
    ws_name = config.get("default_workspace", "")
    if ws_name:
        return staged_dir(ws_name) / "self.md"
    return FALLBACK_DIR / "self.md"


def get_agents_md_path() -> Path | None:
    """
    Return AGENTS.md path from workspace config, or None if not configured.
    """
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


def get_claude_md_path() -> Path | None:
    """
    Return CLAUDE.md path from workspace config, or None if not configured.
    """
    config = _read_config()
    default_ws = config.get("default_workspace")
    if default_ws:
        ws_config = get_workspace_config(default_ws)
        v = ws_config.get("workspace")
        if v:
            p = Path(v) / "CLAUDE.md"
            if p.exists():
                return p
    return None


def resolve_general_instruction_path(session_id: str | None) -> Path | None:
    """
    Return CLAUDE.md if session has a claude_session_id, else AGENTS.md.
    """
    if session_id:
        from .session.resolver import _parse, session_file as _sf
        try:
            data = _parse(_sf(session_id))
            if data.get("claude_session_id"):
                return get_claude_md_path()
        except Exception:
            pass
    return get_agents_md_path()


def get_workspace_path() -> Path:
    """
    Return workspace from workspace config, else fall back to
    documentation root parent or OWRAP_HOME.
    """
    config = _read_config()
    default_ws = config.get("default_workspace")
    if default_ws:
        ws_config = get_workspace_config(default_ws)
        v = ws_config.get("workspace")
        if v:
            return Path(v)
    v = config.get("docs_root")
    if v:
        return Path(v).parent
    return DOCS_DIR.parent


def claude_transcript_path(ccsid: str, workspace_path: Path) -> Path:
    """
    Path to Claude Code's own transcript JSONL for one window (ccsid),
    derived without needing a hook payload: Claude Code stores it at
    ~/.claude/projects/<workspace-path-with-/-as-->/<ccsid>.jsonl.
    """
    project_dir = str(workspace_path).replace("/", "-")
    return Path.home() / ".claude" / "projects" / project_dir / f"{ccsid}.jsonl"


def codex_transcript_path(cid: str) -> Path | None:
    """
    Find the local Codex rollout file for a session ID.
    """
    codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    matches = list((codex_home / "sessions").glob(f"**/rollout-*-{cid}.jsonl"))
    return max(matches, key=lambda path: path.stat().st_mtime) if matches else None


def _resolve_docs_root() -> str | None:
    config = _read_config()
    ws_name = config.get("default_workspace", "")
    root = None
    if ws_name:
        workspace = get_workspace_config(ws_name)
        root = workspace.get("docs_root")
    if not root:
        root = config.get("docs_root")
    return root


def server_state_file(port: int) -> Path:
    return SERVERS_DIR / f"{port}.json"


def context_path(session_id: str) -> Path:
    """
    Return session-scoped context file path.
    """
    return session_dir(session_id) / "context.md"


def format_failure_pointer(failure_code: str, session_id: str | None = None) -> str:
    """
    Format #DO NOW failure message with resolved instruction path and section.
    """
    from .constants import FAILURE_POINTERS
    target, section = FAILURE_POINTERS.get(failure_code, ("self", "Update Context"))
    if target == "self":
        path = get_self_path()
    else:
        path = resolve_general_instruction_path(session_id)
    if path:
        return f"#DO NOW\n{failure_code} — read {path} § {section} and follow it."
    return f"#DO NOW\n{failure_code} — no instruction path found."


def context_lock_path(session_id: str) -> Path:
    """
    Return session-scoped context lock file path.
    """
    return session_dir(session_id) / "context.lock"


def session_ctx_state_path(session_id: str) -> Path:
    """
    Return the session-scoped context-manager state file: ctx_status,
    last dispatch result, per-target sync timestamps, and the per-window
    transcript cursor/touched-entries map — one canonical JSON per
    session, guarded by its own lock (ctx_state_lock_path), separate
    from context.md's, since writers of one rarely need to block on
    the other.
    """
    return session_dir(session_id) / "ctx_state.json"


def ctx_state_lock_path(session_id: str) -> Path:
    """
    Return the session-scoped ctx_state.json lock file path, separate
    from context.md's own lock (context_lock_path).
    """
    return session_dir(session_id) / "ctx_state.lock"
