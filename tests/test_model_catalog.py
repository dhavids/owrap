import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from owrap.utils.dispatch.model_catalog import discover_free_model


def _write_cache(path, provider_models):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "opencode": {"models": provider_models},
    }))


def _model(input_cost=0, output_cost=0):
    return {"cost": {"input": input_cost, "output": output_cost}}


def _live_models(*bare_ids):
    lines = "\n".join(f"opencode/{mid}" for mid in bare_ids)
    return MagicMock(returncode=0, stdout=lines, stderr="")


class TestDiscoverFreeModel:
    def test_prefers_deepseek(self, tmp_path, monkeypatch):
        cache = tmp_path / "models.json"
        _write_cache(cache, {"glm-5-free": _model(), "deepseek-v4-flash-free": _model()})
        monkeypatch.setattr("owrap.utils.dispatch.model_catalog.OPENCODE_MODELS_CACHE", cache)
        with patch(
            "owrap.utils.dispatch.model_catalog.subprocess.run",
            return_value=_live_models("glm-5-free", "deepseek-v4-flash-free"),
        ):
            assert discover_free_model() == "opencode/deepseek-v4-flash-free"

    def test_falls_back_to_known_family_when_no_deepseek(self, tmp_path, monkeypatch):
        cache = tmp_path / "models.json"
        _write_cache(cache, {"big-pickle": _model(), "glm-5-free": _model()})
        monkeypatch.setattr("owrap.utils.dispatch.model_catalog.OPENCODE_MODELS_CACHE", cache)
        with patch(
            "owrap.utils.dispatch.model_catalog.subprocess.run",
            return_value=_live_models("big-pickle", "glm-5-free"),
        ):
            assert discover_free_model() == "opencode/glm-5-free"

    def test_excludes_anonymous_models(self, tmp_path, monkeypatch):
        cache = tmp_path / "models.json"
        _write_cache(cache, {"big-pickle": _model(), "space-bunny-free": _model()})
        monkeypatch.setattr("owrap.utils.dispatch.model_catalog.OPENCODE_MODELS_CACHE", cache)
        with patch(
            "owrap.utils.dispatch.model_catalog.subprocess.run",
            return_value=_live_models("big-pickle", "space-bunny-free"),
        ):
            assert discover_free_model() is None

    def test_excludes_paid_models(self, tmp_path, monkeypatch):
        cache = tmp_path / "models.json"
        _write_cache(cache, {"deepseek-v4-pro": _model(input_cost=1.74, output_cost=3.84)})
        monkeypatch.setattr("owrap.utils.dispatch.model_catalog.OPENCODE_MODELS_CACHE", cache)
        with patch(
            "owrap.utils.dispatch.model_catalog.subprocess.run",
            return_value=_live_models("deepseek-v4-pro"),
        ):
            assert discover_free_model() is None

    def test_discontinued_model_excluded_even_if_still_cached(self, tmp_path, monkeypatch):
        """A model gone from the live list is never picked, even if the
        (stale) local cache still lists it as free."""
        cache = tmp_path / "models.json"
        _write_cache(cache, {
            "deepseek-v4-flash-free": _model(), "mimo-v2.6-flash-free": _model(),
        })
        monkeypatch.setattr("owrap.utils.dispatch.model_catalog.OPENCODE_MODELS_CACHE", cache)
        with patch(
            "owrap.utils.dispatch.model_catalog.subprocess.run",
            return_value=_live_models("mimo-v2.6-flash-free"),
        ):
            assert discover_free_model() == "opencode/mimo-v2.6-flash-free"

    def test_live_model_absent_from_cache_uses_free_suffix_convention(
        self, tmp_path, monkeypatch,
    ):
        cache = tmp_path / "models.json"
        _write_cache(cache, {})
        monkeypatch.setattr("owrap.utils.dispatch.model_catalog.OPENCODE_MODELS_CACHE", cache)
        with patch(
            "owrap.utils.dispatch.model_catalog.subprocess.run",
            return_value=_live_models("glm-6-free"),
        ):
            assert discover_free_model() == "opencode/glm-6-free"

    def test_returns_none_when_cache_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "owrap.utils.dispatch.model_catalog.OPENCODE_MODELS_CACHE",
            tmp_path / "does_not_exist.json",
        )
        with patch(
            "owrap.utils.dispatch.model_catalog.subprocess.run",
            return_value=_live_models("glm-5-free"),
        ):
            assert discover_free_model() == "opencode/glm-5-free"

    def test_returns_none_when_provider_missing_from_cache(self, tmp_path, monkeypatch):
        cache = tmp_path / "models.json"
        cache.write_text(json.dumps({"other-provider": {"models": {}}}))
        monkeypatch.setattr("owrap.utils.dispatch.model_catalog.OPENCODE_MODELS_CACHE", cache)
        with patch(
            "owrap.utils.dispatch.model_catalog.subprocess.run",
            return_value=_live_models("glm-5-free"),
        ):
            assert discover_free_model() == "opencode/glm-5-free"

    def test_returns_none_on_corrupt_cache(self, tmp_path, monkeypatch):
        cache = tmp_path / "models.json"
        cache.write_text("not valid json")
        monkeypatch.setattr("owrap.utils.dispatch.model_catalog.OPENCODE_MODELS_CACHE", cache)
        with patch(
            "owrap.utils.dispatch.model_catalog.subprocess.run",
            return_value=_live_models("glm-5-free"),
        ):
            assert discover_free_model() == "opencode/glm-5-free"

    def test_returns_none_when_opencode_not_found(self):
        with patch(
            "owrap.utils.dispatch.model_catalog.subprocess.run", side_effect=FileNotFoundError,
        ):
            assert discover_free_model() is None

    def test_returns_none_on_timeout(self):
        with patch(
            "owrap.utils.dispatch.model_catalog.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="opencode models", timeout=2),
        ):
            assert discover_free_model() is None

    def test_returns_none_when_live_list_empty(self):
        with patch(
            "owrap.utils.dispatch.model_catalog.subprocess.run",
            return_value=MagicMock(returncode=1, stdout="", stderr="boom"),
        ):
            assert discover_free_model() is None
