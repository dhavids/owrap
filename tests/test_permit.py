import io
import json
from unittest.mock import patch

import pytest

from owrap.commands.permit import PermitCmdRunner, PermitRunner


@pytest.fixture
def permit_setup(tmp_path):
    """
    Isolate CONFIGS_DIR/BASE_CONFIG_FILE and write a base+workspace config.
    """
    configs_dir = tmp_path / "configs"
    configs_dir.mkdir()
    base_config = configs_dir / "base.json"
    base_config.write_text(json.dumps({"default_workspace": "testws"}))
    ws_config = configs_dir / "testws.json"
    ws_config.write_text(json.dumps({"workspace": "/tmp/testws"}))

    with patch("owrap.utils.paths.CONFIGS_DIR", configs_dir), \
         patch("owrap.utils.paths.BASE_CONFIG_FILE", base_config), \
         patch("owrap.utils.paths._config_cache", None), \
         patch("owrap.utils.paths._config_cache_stat", None):
        yield configs_dir, ws_config


def _permit_path(configs_dir):
    return configs_dir / "testws_permit.json"


def _stdin_with(tool_name, command):
    return io.StringIO(json.dumps({
        "tool_name": tool_name,
        "tool_input": {"command": command},
    }))


class TestPermitRunner:
    @pytest.mark.parametrize("rules,bypass_all,command,expected", [
        ([], True, "rm -rf /", "allow"),
        (["Bash(git log *)"], False, "git log -5", "allow"),
        (["Bash(git log *)"], False, "rm -rf /", "deny"),
    ], ids=["bypass_all_allows_any_tool", "rule_match_allows", "no_rule_match_denies"])
    def test_decision(
        self, permit_setup, capsys, monkeypatch, rules, bypass_all, command, expected,
    ):
        configs_dir, _ = permit_setup
        _permit_path(configs_dir).write_text(json.dumps({
            "orun_cmd": "~/bin/orun", "rules": rules, "bypass_all": bypass_all,
        }))
        monkeypatch.setattr("sys.stdin", _stdin_with("Bash", command))
        PermitRunner().run()
        out = json.loads(capsys.readouterr().out)
        assert out["hookSpecificOutput"]["permissionDecision"] == expected


class TestPermitCmdRunner:
    def test_status_no_permit_file(self, permit_setup, capsys):
        PermitCmdRunner().run_status()
        assert "run `owrap sync`" in capsys.readouterr().out

    def test_bypass_all_on_then_status_reflects_it(self, permit_setup, capsys):
        configs_dir, ws_config = permit_setup
        with patch("owrap.staging.CONFIGS_DIR", configs_dir), \
             patch(
                 "owrap.staging.staged_dir",
                 lambda name: configs_dir.parent / "staged" / name,
             ):
            PermitCmdRunner().run_bypass_all("on")
        capsys.readouterr()

        cfg = json.loads(ws_config.read_text())
        assert cfg["permit_bypass_all"] is True

        permit = json.loads(_permit_path(configs_dir).read_text())
        assert permit["bypass_all"] is True

        PermitCmdRunner().run_status()
        assert "ON for 'testws'" in capsys.readouterr().out

    def test_bypass_all_invalid_state_errors(self, permit_setup, capsys):
        with pytest.raises(SystemExit) as exc:
            PermitCmdRunner().run_bypass_all("maybe")
        assert exc.value.code == 2
        assert "expected 'on' or 'off'" in capsys.readouterr().out
