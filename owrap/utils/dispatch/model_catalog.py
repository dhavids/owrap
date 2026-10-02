import json
import subprocess
from pathlib import Path

OPENCODE_MODELS_CACHE = Path.home() / ".cache" / "opencode" / "models.json"
MODELS_LOOKUP_TIMEOUT_S = 2

# Recognizable model-family name fragments, for excluding anonymous/unbranded
# free-tier preview models (e.g. "big-pickle", "space-bunny-free") from
# auto-selection — only pick from labs with an actual track record.
_KNOWN_FAMILIES = (
    "deepseek", "qwen", "glm", "kimi", "minimax", "mimo",
    "nemotron", "hunyuan", "hy3", "hy4", "grok",
)


def discover_free_model(
    provider: str = "opencode", prefer: str = "deepseek",
) -> str | None:
    """
    Pick a currently-live free model, preferring a named/branded family
    (prefer, then _KNOWN_FAMILIES) over an anonymous preview model.

    Existence is checked against a live `opencode models <provider>` call
    (models do get discontinued) — the local cache is used only for cost
    data, as a best-effort cross-reference, falling back to the `-free`
    naming convention when a live model isn't in the cache at all.

    Returns None if opencode isn't available, the lookup times out, or no
    recognizable free model is found — callers must not assume a value is
    always returned, and must never substitute a hardcoded model name.
    """
    live_ids = _live_model_ids(provider)
    if not live_ids:
        return None

    cost_by_id = _cached_cost_by_id(provider)
    free_ids = [
        mid for mid in live_ids
        if _is_free(mid, cost_by_id)
    ]

    preferred = sorted(mid for mid in free_ids if prefer in mid.lower())
    if preferred:
        return f"{provider}/{preferred[0]}"

    branded = sorted(
        mid for mid in free_ids
        if any(family in mid.lower() for family in _KNOWN_FAMILIES)
    )
    if branded:
        return f"{provider}/{branded[0]}"

    return None


def _live_model_ids(provider: str) -> list:
    """
    Return bare model ids (no provider prefix) opencode currently lists
    for provider, or [] if the lookup fails or times out.
    """
    try:
        result = subprocess.run(
            ["opencode", "models", provider],
            capture_output=True, text=True, timeout=MODELS_LOOKUP_TIMEOUT_S,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []
    if result.returncode != 0:
        return []

    prefix = f"{provider}/"
    return [
        line.strip()[len(prefix):]
        for line in result.stdout.splitlines()
        if line.strip().startswith(prefix)
    ]


def _cached_cost_by_id(provider: str) -> dict:
    """
    Return {model_id: (input_cost, output_cost)} from the local opencode
    model cache for provider, or {} if the cache is missing/unreadable.
    """
    if not OPENCODE_MODELS_CACHE.exists():
        return {}
    try:
        catalog = json.loads(OPENCODE_MODELS_CACHE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}

    provider_info = catalog.get(provider)
    models = provider_info.get("models") if isinstance(provider_info, dict) else None
    if not isinstance(models, dict):
        return {}

    costs = {}
    for mid, info in models.items():
        if isinstance(info, dict) and isinstance(info.get("cost"), dict):
            costs[mid] = (info["cost"].get("input", 1), info["cost"].get("output", 1))
    return costs


def _is_free(model_id: str, cost_by_id: dict) -> bool:
    """
    A model is free if the (possibly stale) cache says its cost is
    0/0, or — for a live model absent from the cache — its id follows
    the catalog's "-free" naming convention.
    """
    cost = cost_by_id.get(model_id)
    if cost is not None:
        return cost == (0, 0)
    return model_id.endswith("-free")
