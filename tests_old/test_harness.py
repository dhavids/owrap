import json
from unittest.mock import patch

import pytest

from owrap.commands.sync import SyncRunner
from owrap.utils.harness import merge_claude_settings, merge_codex_hooks


def test_claude_settings_keep_user_values_and_replace_owrap_hooks():
    existing = {
        "model": "user-model",
        "permissions": {
            "defaultMode": "default",
            "allow": ["Bash(user-tool *)"],
            "deny": ["Bash(danger *)"],
        },
        "hooks": {
            "PreToolUse": [{
                "matcher": "Bash",
                "hooks": [
                    {"type": "command", "command": "user-check"},
                    {"type": "command", "command": "~/bin/owrap p"},
                ],
            }],
            "Stop": [{
                "hooks": [{"type": "command", "command": "user-stop"}],
            }],
        },
    }
    managed = {
        "permissions": {
            "defaultMode": "dontAsk",
            "allow": ["Read"],
        },
        "hooks": {
            "PreToolUse": [{
                "matcher": "^Bash$",
                "hooks": [{"type": "command", "command": "/usr/bin/owrap p"}],
            }],
        },
    }

    result = json.loads(merge_claude_settings(
        json.dumps(existing), json.dumps(managed),
    ))

    assert result["model"] == "user-model"
    assert result["permissions"] == {
        "defaultMode": "default",
        "allow": ["Bash(user-tool *)", "Read"],
        "deny": ["Bash(danger *)"],
    }
    assert result["hooks"]["Stop"] == existing["hooks"]["Stop"]
    assert result["hooks"]["PreToolUse"][0]["hooks"] == [
        {"type": "command", "command": "user-check"},
    ]
    assert len(result["hooks"]["PreToolUse"]) == 2
    assert json.loads(merge_claude_settings(
        json.dumps(result), json.dumps(managed),
    )) == result


def test_sync_preserves_project_settings_and_codex_config(tmp_path):
    workspace = tmp_path / "workspace"
    claude_dir = workspace / ".claude"
    codex_dir = workspace / ".codex"
    claude_dir.mkdir(parents=True)
    codex_dir.mkdir()
    original = {
        "model": "user-model",
        "permissions": {"allow": ["Bash(user-tool *)"]},
        "hooks": {"Stop": [{
            "hooks": [{"type": "command", "command": "user-stop"}],
        }]},
    }
    (claude_dir / "settings.local.json").write_text(json.dumps(original))
    project_settings = dict(original)
    project_settings["hooks"] = {
        **original["hooks"],
        "PreCompact": [{
            "hooks": [{"type": "command", "command": "~/bin/owrap ctx-hook"}],
        }],
    }
    (claude_dir / "settings.json").write_text(json.dumps(project_settings))
    codex_config = "model = 'user-model'\n"
    (codex_dir / "config.toml").write_text(codex_config)
    codex_hooks = {
        "custom": {"keep": True},
        "hooks": {"Stop": [{
            "hooks": [{"type": "command", "command": "user-stop"}],
        }]},
    }
    (codex_dir / "hooks.json").write_text(json.dumps(codex_hooks))
    staged = tmp_path / "staged"
    staged.mkdir()
    (staged / "claude").mkdir()
    (staged / "codex").mkdir()
    (staged / "claude" / "settings.json").write_text(json.dumps({
        "permissions": {"defaultMode": "dontAsk", "allow": ["Read"]},
        "hooks": {"PreCompact": [{
            "matcher": "auto|manual",
            "hooks": [{"type": "command", "command": "~/bin/owrap ctx-hook"}],
        }]},
    }))
    (staged / "codex" / "hooks.json").write_text(json.dumps({
        "hooks": {"PreCompact": [{
            "matcher": "auto|manual",
            "hooks": [{"type": "command", "command": "/usr/bin/owrap ctx-hook"}],
        }]},
    }))
    runner = SyncRunner()
    with patch.object(runner, "_active_workspace", return_value=("dev", "abc123")), \
         patch.object(runner, "_sync_global_read_permission"), \
         patch("owrap.commands.sync.get_workspace_config", return_value={
             "workspace": str(workspace),
         }), \
         patch("owrap.commands.sync.stage_all", return_value=staged):
        with pytest.raises(SystemExit) as exc:
            runner.run()
    assert exc.value.code == 0

    settings = json.loads((claude_dir / "settings.local.json").read_text())
    assert settings["model"] == "user-model"
    assert settings["permissions"]["allow"] == ["Bash(user-tool *)", "Read"]
    assert settings["hooks"]["Stop"] == original["hooks"]["Stop"]
    assert "PreCompact" in settings["hooks"]
    project = json.loads((claude_dir / "settings.json").read_text())
    assert project["model"] == "user-model"
    assert project["hooks"] == original["hooks"]
    assert (codex_dir / "config.toml").read_text() == codex_config
    installed_hooks = json.loads((codex_dir / "hooks.json").read_text())
    assert installed_hooks["custom"] == codex_hooks["custom"]
    assert installed_hooks["hooks"]["Stop"] == codex_hooks["hooks"]["Stop"]
    assert "PreCompact" in installed_hooks["hooks"]


def test_codex_hook_merge_preserves_user_hooks_and_is_repeatable():
    original = {
        "custom": {"keep": True},
        "hooks": {
            "PreCompact": [{
                "matcher": "auto",
                "hooks": [{"type": "command", "command": "user-compact"}],
            }],
            "Stop": [{
                "hooks": [{"type": "command", "command": "user-stop"}],
            }],
        },
    }
    managed = {
        "hooks": {
            "PreCompact": [{
                "matcher": "auto|manual",
                "hooks": [{
                    "type": "command",
                    "command": "/usr/bin/owrap ctx-hook",
                    "statusMessage": "Saving owrap context",
                }],
            }],
        },
    }
    first = merge_codex_hooks(json.dumps(original), json.dumps(managed))
    second = merge_codex_hooks(first, json.dumps(managed))

    assert second == first
    result = json.loads(second)
    assert result["custom"] == original["custom"]
    assert result["hooks"]["Stop"] == original["hooks"]["Stop"]
    assert result["hooks"]["PreCompact"][0] == original["hooks"]["PreCompact"][0]
    assert result["hooks"]["PreCompact"][1]["matcher"] == "auto|manual"
