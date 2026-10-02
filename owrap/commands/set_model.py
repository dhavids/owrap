import json
import subprocess
import sys

from ..staging import stage_all
from ..utils.match import require_unique_match
from ..utils.paths import CONFIGS_DIR, _read_config

MODELS_LOOKUP_TIMEOUT_S = 2

_VALID_SLOTS = (
    "runner", "context_manager", "context_fallback", "daemon_default",
)


class SetModelRunner:
    """
    Search available opencode models and set one as a workspace model slot.
    """

    def run(self, slot: str, query: str, workspace: str = None):
        """
        Resolve query against live model names for the given slot; set it
        on an exact single match, otherwise report none/ambiguous and exit.
        """
        if slot not in _VALID_SLOTS:
            print(f"ERROR: unknown slot '{slot}'. Valid: {', '.join(_VALID_SLOTS)}")
            sys.exit(2)

        ws_name = workspace or _read_config().get("default_workspace", "")
        if not ws_name:
            print("ERROR: no workspace given and no default_workspace configured.")
            sys.exit(2)

        models = self._lookup_models()
        matches = sorted(m for m in models if query.lower() in m.lower())
        model = require_unique_match(matches, "model", query)
        cfg_path = CONFIGS_DIR / f"{ws_name}.json"
        if not cfg_path.exists():
            print(f"ERROR: no config file for workspace '{ws_name}'")
            sys.exit(2)

        cfg = json.loads(cfg_path.read_text())
        key = f"{slot}_model"
        cfg[key] = model
        cfg_path.write_text(json.dumps(cfg, indent=2))

        stage_all(ws_name)

        print(f"SET {key}={model} for workspace '{ws_name}'")


    # Private Methods

    def _lookup_models(self) -> list:
        """
        Return every 'provider/model-id' string opencode currently offers,
        via a live `opencode models` call bounded to MODELS_LOOKUP_TIMEOUT_S.
        """
        try:
            result = subprocess.run(
                ["opencode", "models"],
                capture_output=True, text=True,
                timeout=MODELS_LOOKUP_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired:
            print(
                f"ERROR: timed out after {MODELS_LOOKUP_TIMEOUT_S}s "
                f"looking for models.",
            )
            sys.exit(2)
        except FileNotFoundError:
            print("ERROR: 'opencode' command not found on PATH.")
            sys.exit(2)

        if result.returncode != 0:
            print(f"ERROR: opencode models failed: {result.stderr.strip()}")
            sys.exit(2)

        return [line.strip() for line in result.stdout.splitlines() if line.strip()]
