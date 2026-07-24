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

class TestRenderAllowedSection:
    def test_no_oread_produces_3_command_lines_6_file_lines(self):
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

        assert len(cmd_lines) == 3
        assert len(file_lines) == 6


class TestStageAll:
    def test_stage_all_marl_produces_valid_settings_and_merged_claude(self):
        from owrap.staging import stage_all
        from pathlib import Path

        from owrap.utils.paths import CONFIGS_DIR

        out_dir = stage_all("marl")

        settings_path = out_dir / "settings.json"
        assert settings_path.exists()
        data = json.loads(settings_path.read_text())
        assert "permissions" in data
        assert "Grep" in data["permissions"]["allow"]
        assert "Read" in data["permissions"]["allow"]

        permit_path = CONFIGS_DIR / "marl_permit.json"
        assert permit_path.exists()
        permit_data = json.loads(permit_path.read_text())
        assert "Bash(cd *)" in permit_data["rules"]

        claude_path = Path("/home/humble/marl/CLAUDE.md")
        assert claude_path.exists()
        content = claude_path.read_text()

        # `### Commands`/`### Files` subsections are no longer rendered into planner.md
        # (ALLOWED_COMMANDS/ALLOWED_FILES placeholders aren't referenced by any template);
        # just confirm the merge produced the current flat `## Allowed` section.
        assert "## Allowed" in content
        assert "## Dispatch Tooling" in content
