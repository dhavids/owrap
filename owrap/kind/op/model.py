import json
import subprocess

from . import Op
from ...utils.match import require_unique_match
from ...utils.paths import CONFIGS_DIR, _read_config
from ...utils.staging import stage_all

MODEL_SLOTS = ("runner", "context_manager", "context_fallback", "daemon_default")
LOOKUP_TIMEOUT_S = 2


class Model(Op):
    """
    Set the model for one of a workspace's model slots, by matching
    a substring against the harness's available model names.
    """

    kind = "model"

    usage = {
        "set": {
            "usage": "<slot> <query> [workspace]",
            "args": [
                ("slot", f"one of {', '.join(MODEL_SLOTS)}"),
                ("query", "substring to search for in available model names"),
            ],
            "examples": ["runner haiku"],
        },
    }

    messages = {"set": "{message}"}


    # Public Methods

    def set(self, slot: str = None, query: str = None, workspace: str = None) -> None:
        if query is None:
            self._usage("set")
        if slot not in MODEL_SLOTS:
            self._fail(f"unknown slot '{slot}'. Valid: {', '.join(MODEL_SLOTS)}")
        ws_name = workspace or _read_config().get("default_workspace", "")
        if not ws_name:
            self._fail("no workspace given and no default_workspace configured.")

        models = self._lookup_models()
        matches = sorted(m for m in models if query.lower() in m.lower())
        model = require_unique_match(matches, "model", query)
        cfg_path = CONFIGS_DIR / f"{ws_name}.json"
        if not cfg_path.exists():
            self._fail(f"no config file for workspace '{ws_name}'")

        cfg = json.loads(cfg_path.read_text())
        key = f"{slot}_model"
        cfg[key] = model
        cfg_path.write_text(json.dumps(cfg, indent=2))
        stage_all(ws_name)
        self._ok("set", message=f"SET {key}={model} for workspace '{ws_name}'")


    # Private Methods

    def _lookup_models(self) -> list:
        try:
            result = subprocess.run(
                ["opencode", "models"], capture_output=True, text=True,
                timeout=LOOKUP_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired:
            self._fail(f"timed out after {LOOKUP_TIMEOUT_S}s looking for models.")
        except FileNotFoundError:
            self._fail("'opencode' command not found on PATH.")
        if result.returncode != 0:
            self._fail(f"opencode models failed: {result.stderr.strip()}")
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]
