import json
from unittest.mock import patch

import pytest


class TestRenderRuleArray:
    def test_allow_groups_no_oread_contains_expected_rules(self):
        from owrap.staging import load_permission_groups, render_rule_array, resolve_placeholders
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

    def test_deny_groups_no_oread_equals_bash_rm_only(self):
        from owrap.staging import load_permission_groups, render_rule_array, resolve_placeholders
        from owrap.utils.paths import get_workspace_config

        config = get_workspace_config("marl")
        placeholders = resolve_placeholders(config, "marl")
        flags = {"OREAD": False, "NO_OREAD": True}

        groups = load_permission_groups("deny.json")
        rendered = render_rule_array(groups, flags, placeholders)
        parsed = json.loads(rendered)

        assert parsed == ["Bash(rm *)"]


class TestRenderAllowedSection:
    def test_no_oread_produces_2_command_lines_6_file_lines(self):
        from owrap.staging import load_permission_groups, render_allowed_section, resolve_placeholders
        from owrap.utils.paths import get_workspace_config

        config = get_workspace_config("marl")
        placeholders = resolve_placeholders(config, "marl")
        flags = {"OREAD": False, "NO_OREAD": True}

        groups = load_permission_groups("allow.json")
        commands = render_allowed_section(groups, flags, placeholders, "commands")
        files = render_allowed_section(groups, flags, placeholders, "files")

        cmd_lines = [l for l in commands.strip().split("\n") if l.strip().startswith("-")]
        file_lines = [l for l in files.strip().split("\n") if l.strip().startswith("-")]

        assert len(cmd_lines) == 2
        assert len(file_lines) == 6


class TestStageAll:
    def test_stage_all_marl_produces_valid_settings_and_merged_claude(self):
        from owrap.staging import stage_all
        from pathlib import Path

        out_dir = stage_all("marl")

        settings_path = out_dir / "settings.json"
        assert settings_path.exists()
        data = json.loads(settings_path.read_text())
        assert "permissions" in data
        assert "Bash(cd *)" in data["permissions"]["allow"]
        assert data["permissions"]["deny"] == ["Bash(rm *)"]

        claude_path = Path("/home/humble/marl/CLAUDE.md")
        assert claude_path.exists()
        content = claude_path.read_text()

        section_start = content.find("### Commands")
        section_files = content.find("### Files")
        section_end = content.find("## Dispatch Tooling")
        assert section_start >= 0
        assert section_files >= 0
        assert section_end >= 0

        commands_area = content[section_start:section_files]
        files_area = content[section_files:section_end]

        cmd_bullets = [l for l in commands_area.split("\n") if l.strip().startswith("-")]
        file_bullets = [l for l in files_area.split("\n") if l.strip().startswith("-")]

        assert len(cmd_bullets) == 2
        assert len(file_bullets) == 6
