import json
from unittest.mock import patch

import pytest


class TestRenderRuleArray:
    def test_allow_groups_no_oread_contains_expected_rules(self):
        from owrap.staging import (
            load_permission_groups, render_rule_array, resolve_placeholders,
        )
        from owrap.utils.paths import get_workspace_config

        config = get_workspace_config("marl")
        placeholders = resolve_placeholders(config, "marl")
        flags = {"OREAD": False, "NO_OREAD": True}

        groups = load_permission_groups("allow.json")
        rendered = render_rule_array(groups, flags, placeholders)
        parsed = json.loads(rendered)

        assert "Bash(cd *)" in parsed
        assert "Read" in parsed
        assert "Bash(grep *)" in parsed

class TestRenderAllowedSection:
    def test_no_oread_produces_3_command_lines_6_file_lines(self):
        from owrap.staging import (
            load_permission_groups, render_allowed_section, resolve_placeholders,
        )
        from owrap.utils.paths import get_workspace_config

        config = get_workspace_config("marl")
        placeholders = resolve_placeholders(config, "marl")
        flags = {"OREAD": False, "NO_OREAD": True}

        groups = load_permission_groups("allow.json")
        commands = render_allowed_section(groups, flags, placeholders, "commands")
        files = render_allowed_section(groups, flags, placeholders, "files")

        cmd_lines = [l for l in commands.strip().split("\n") if l.strip().startswith("-")]
        file_lines = [l for l in files.strip().split("\n") if l.strip().startswith("-")]

        assert len(cmd_lines) == 3
        assert len(file_lines) == 6


class TestStageAll:
    def test_stage_all_marl_produces_settings_hooks_and_merged_agents(self, tmp_path):
        from owrap.staging import stage_all
        from pathlib import Path

        fixed_config = {
            "runner_allow_all": True,
            "owrap_runner_enabled": True,
            "owrap_context_manager_enabled": True,
            "runner_use_oread": False,
            "context_injection_enabled": True,
            "research_root": str(tmp_path / "docs" / "research"),
            "workspace": str(tmp_path / "marl"),
            "exec_model": "opencode-go/qwen3.6-plus",
            "daemon_interval_s": 10,
            "bin_dir": "~/bin",
            "updr_every_orun": 15,
            "max_requests": 10,
        }

        fake_configs = tmp_path / "configs"
        fake_configs.mkdir()
        ws_path = tmp_path / "marl"
        codex_dir = ws_path / ".codex"
        codex_dir.mkdir(parents=True)
        other_hook = {"type": "command", "command": "check-bash"}
        (codex_dir / "hooks.json").write_text(json.dumps({
            "hooks": {"PreToolUse": [{
                "matcher": "^Bash$",
                "hooks": [
                    other_hook,
                    {
                        "type": "command",
                        "command": "old-owrap",
                        "statusMessage": "Checking owrap permission",
                    },
                ],
            }]},
        }))

        with patch("owrap.staging.get_workspace_config", return_value=fixed_config), \
             patch("owrap.staging.CONFIGS_DIR", fake_configs), \
             patch("owrap.staging.staged_dir", return_value=tmp_path / "staged"):
            out_dir = stage_all("marl")

        settings_path = out_dir / "settings.json"
        assert settings_path.exists()
        data = json.loads(settings_path.read_text())
        assert "permissions" in data
        assert "Grep" in data["permissions"]["allow"]
        assert "Read" in data["permissions"]["allow"]

        permit_path = fake_configs / "marl_permit.json"
        assert permit_path.exists()
        permit_data = json.loads(permit_path.read_text())
        assert "Bash(cd *)" in permit_data["rules"]

        codex_hooks = json.loads((out_dir / "codex_hooks.json").read_text())
        groups = codex_hooks["hooks"]["PreToolUse"]
        assert len(groups) == 2
        assert groups[0]["hooks"] == [other_hook]
        assert groups[1]["matcher"] == "^Bash$"
        assert groups[1]["hooks"][0]["command"] == (
            f"{Path.home() / 'bin' / 'owrap'} p --workspace marl"
        )
        approval_groups = codex_hooks["hooks"]["PermissionRequest"]
        assert len(approval_groups) == 1
        assert approval_groups[0]["matcher"] == "^Bash$"
        assert approval_groups[0]["hooks"][0]["command"] == (
            f"{Path.home() / 'bin' / 'owrap'} p --workspace marl"
        )

        claude_path = ws_path / "CLAUDE.md"
        assert claude_path.exists()
        content = claude_path.read_text()

        assert "## Allowed" in content
        assert "## Runner Tooling" in content
