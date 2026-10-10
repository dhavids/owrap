import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from owrap.commands.set_model import SetModelRunner


@pytest.fixture
def set_model_setup(tmp_path, monkeypatch):
    configs_dir = tmp_path / "configs"
    configs_dir.mkdir()
    (configs_dir / "base.json").write_text(json.dumps({"default_workspace": "testws"}))
    ws_config = configs_dir / "testws.json"
    ws_config.write_text(json.dumps({"workspace": "/tmp/testws"}))

    monkeypatch.setattr("owrap.utils.paths.CONFIGS_DIR", configs_dir)
    monkeypatch.setattr("owrap.utils.paths.BASE_CONFIG_FILE", configs_dir / "base.json")
    monkeypatch.setattr("owrap.commands.set_model.CONFIGS_DIR", configs_dir)
    return configs_dir, ws_config


def _mock_models(lines, returncode=0):
    return MagicMock(returncode=returncode, stdout="\n".join(lines), stderr="")


class TestSetModelRunner:
    def test_unique_match_sets_config(self, set_model_setup, capsys):
        configs_dir, ws_config = set_model_setup
        models = _mock_models([
            "opencode-go/qwen3.8-max", "opencode/deepseek-v4-flash-free",
        ])
        with patch("owrap.commands.set_model.subprocess.run", return_value=models), \
             patch("owrap.staging.CONFIGS_DIR", configs_dir), \
             patch(
                 "owrap.staging.staged_dir",
                 lambda name: configs_dir.parent / "staged" / name,
             ):
            SetModelRunner().run("runner", "qwen3.8-max", workspace="testws")

        cfg = json.loads(ws_config.read_text())
        assert cfg["runner_model"] == "opencode-go/qwen3.8-max"
        assert "SET runner_model=opencode-go/qwen3.8-max" in capsys.readouterr().out

    def test_ambiguous_match_does_not_set_config(self, set_model_setup, capsys):
        configs_dir, ws_config = set_model_setup
        models = _mock_models([
            "opencode-go/qwen3.7-plus", "opencode-go/qwen3.8-flash",
            "opencode-go/qwen3.8-max",
        ])
        with patch("owrap.commands.set_model.subprocess.run", return_value=models):
            with pytest.raises(SystemExit) as exc:
                SetModelRunner().run("runner", "qwen", workspace="testws")
        assert exc.value.code == 2
        out = capsys.readouterr().out
        assert "AMBIGUOUS" in out
        assert "opencode-go/qwen3.7-plus" in out
        cfg = json.loads(ws_config.read_text())
        assert "runner_model" not in cfg

    def test_no_match_errors(self, set_model_setup, capsys):
        models = _mock_models(["opencode-go/qwen3.8-max"])
        with patch("owrap.commands.set_model.subprocess.run", return_value=models):
            with pytest.raises(SystemExit) as exc:
                SetModelRunner().run("runner", "totally-nonexistent", workspace="testws")
        assert exc.value.code == 2
        assert "no model matches" in capsys.readouterr().out

    def test_invalid_slot_errors(self, set_model_setup, capsys):
        with pytest.raises(SystemExit) as exc:
            SetModelRunner().run("bogus-slot", "qwen", workspace="testws")
        assert exc.value.code == 2
        assert "unknown slot" in capsys.readouterr().out

    def test_timeout_errors(self, set_model_setup, capsys):
        with patch(
            "owrap.commands.set_model.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="opencode models", timeout=2),
        ):
            with pytest.raises(SystemExit) as exc:
                SetModelRunner().run("runner", "qwen", workspace="testws")
        assert exc.value.code == 2
        assert "timed out after 2s" in capsys.readouterr().out

    def test_opencode_not_found_errors(self, set_model_setup, capsys):
        with patch(
            "owrap.commands.set_model.subprocess.run", side_effect=FileNotFoundError,
        ):
            with pytest.raises(SystemExit) as exc:
                SetModelRunner().run("runner", "qwen", workspace="testws")
        assert exc.value.code == 2
        assert "not found on PATH" in capsys.readouterr().out

    def test_no_workspace_given_or_configured_errors(self, tmp_path, monkeypatch, capsys):
        configs_dir = tmp_path / "configs"
        configs_dir.mkdir()
        (configs_dir / "base.json").write_text(json.dumps({}))
        monkeypatch.setattr("owrap.utils.paths.CONFIGS_DIR", configs_dir)
        monkeypatch.setattr(
            "owrap.utils.paths.BASE_CONFIG_FILE", configs_dir / "base.json",
        )
        with pytest.raises(SystemExit) as exc:
            SetModelRunner().run("runner", "qwen")
        assert exc.value.code == 2
        assert "no workspace given" in capsys.readouterr().out
