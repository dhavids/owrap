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

    @pytest.mark.parametrize("bypass_all,expected", [
        (True, "allow"),
        (False, "deny"),
    ])
    def test_codex_permission_request(
        self, permit_setup, capsys, monkeypatch, bypass_all, expected,
    ):
        configs_dir, _ = permit_setup
        _permit_path(configs_dir).write_text(json.dumps({
            "rules": [], "bypass_all": bypass_all,
        }))
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({
            "hook_event_name": "PermissionRequest",
            "tool_name": "Bash",
            "tool_input": {"command": "owrap ctx"},
            "cwd": "/tmp/testws",
        })))

        PermitRunner().run(workspace_name="testws")

        output = json.loads(capsys.readouterr().out)["hookSpecificOutput"]
        assert output["hookEventName"] == "PermissionRequest"
        assert output["decision"]["behavior"] == expected

    def test_codex_uses_its_own_staged_rules(
        self, permit_setup, capsys, monkeypatch,
    ):
        configs_dir, _ = permit_setup
        _permit_path(configs_dir).write_text(json.dumps({
            "rules": ["Bash(git log *)"], "bypass_all": False,
        }))
        (configs_dir / "testws_codex_permit.json").write_text(json.dumps({
            "rules": ["Bash(git status)"], "bypass_all": False,
        }))
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({
            "hook_event_name": "PermissionRequest",
            "tool_name": "Bash",
            "tool_input": {"command": "git log -1"},
            "cwd": "/tmp/testws",
        })))

        PermitRunner().run(workspace_name="testws")

        output = json.loads(capsys.readouterr().out)["hookSpecificOutput"]
        assert output["decision"]["behavior"] == "deny"

    def test_session_id_selects_codex_permission_response(
        self, permit_setup, capsys, monkeypatch, tmp_path,
    ):
        configs_dir, _ = permit_setup
        _permit_path(configs_dir).write_text(json.dumps({"bypass_all": True}))
        pointer_dir = tmp_path / "by_codex_session_id"
        pointer_dir.mkdir()
        (pointer_dir / "codex-123").write_text("abc123")
        monkeypatch.setattr(
            "owrap.utils.session.resolver.BY_CODEX_SESSION_ID_DIR",
            pointer_dir,
        )
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({
            "session_id": "codex-123",
            "hook_event_name": "PermissionRequest",
            "tool_name": "Bash",
            "tool_input": {"command": "owrap ctx"},
        })))

        PermitRunner().run()

        output = json.loads(capsys.readouterr().out)["hookSpecificOutput"]
        assert output == {
            "hookEventName": "PermissionRequest",
            "decision": {"behavior": "allow"},
        }

    def test_claude_session_id_keeps_pre_tool_use_response(
        self, permit_setup, capsys, monkeypatch, tmp_path,
    ):
        configs_dir, _ = permit_setup
        _permit_path(configs_dir).write_text(json.dumps({"bypass_all": True}))
        pointer_dir = tmp_path / "by_ccsid"
        pointer_dir.mkdir()
        (pointer_dir / "claude-123").write_text("abc123")
        monkeypatch.setattr(
            "owrap.utils.session.resolver.BY_CCSID_DIR",
            pointer_dir,
        )
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({
            "session_id": "claude-123",
            "hook_event_name": "PermissionRequest",
            "tool_name": "Bash",
            "tool_input": {"command": "owrap ctx"},
        })))

        PermitRunner().run()

        output = json.loads(capsys.readouterr().out)["hookSpecificOutput"]
        assert output == {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
        }

    @pytest.mark.parametrize("bypass_all", [True, False])
    def test_codex_pre_tool_use_allows_without_output(
        self, permit_setup, capsys, monkeypatch, bypass_all,
    ):
        configs_dir, _ = permit_setup
        _permit_path(configs_dir).write_text(json.dumps({
            "rules": ["Bash(git status)"], "bypass_all": bypass_all,
        }))
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({
            "session_id": "codex-123",
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "git status"},
            "cwd": "/tmp/testws",
        })))

        PermitRunner().run(workspace_name="testws")

        assert capsys.readouterr().out == ""


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
        codex_permit = json.loads(
            (configs_dir / "testws_codex_permit.json").read_text()
        )
        assert codex_permit["bypass_all"] is True

        PermitCmdRunner().run_status()
        assert "ON for 'testws'" in capsys.readouterr().out

    def test_bypass_all_invalid_state_errors(self, permit_setup, capsys):
        with pytest.raises(SystemExit) as exc:
            PermitCmdRunner().run_bypass_all("maybe")
        assert exc.value.code == 2
        assert "expected 'on' or 'off'" in capsys.readouterr().out
