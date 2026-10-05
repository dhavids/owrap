import json
from unittest.mock import patch


def test_staged_cache_moves_under_runtime(tmp_path):
    from owrap import staging

    legacy = tmp_path / "staged" / "workspace"
    legacy.mkdir(parents=True)
    (legacy / "self.md").write_text("old")
    current = tmp_path / "runtime" / "staged"

    with (
        patch("owrap.staging.OWRAP_HOME", tmp_path),
        patch(
            "owrap.staging.staged_dir",
            side_effect=lambda name: current / name,
        ),
    ):
        staging._migrate_staged_cache()

    assert (current / "workspace" / "self.md").read_text() == "old"
    assert not (tmp_path / "staged").exists()


class TestRenderRuleArray:
    def test_allow_groups_no_oread_contains_expected_rules(self):
        from owrap.staging import (
            load_permission_groups, render_rule_array, resolve_placeholders,
        )
        from owrap.utils.paths import get_workspace_config

        config = get_workspace_config("marl")
        placeholders = resolve_placeholders(config, "marl")
        flags = {"OREAD": False, "NO_OREAD": True}

        groups = load_permission_groups("claude")
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

        groups = load_permission_groups("claude")
        commands = render_allowed_section(groups, flags, placeholders, "commands")
        files = render_allowed_section(groups, flags, placeholders, "files")

        cmd_lines = [l for l in commands.strip().split("\n") if l.strip().startswith("-")]
        file_lines = [l for l in files.strip().split("\n") if l.strip().startswith("-")]

        assert len(cmd_lines) == 3
        assert len(file_lines) == 6


class TestStageAll:
    def test_stage_all_marl_produces_settings_hooks_and_merged_agents(self, tmp_path):
        from owrap.staging import stage_all
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
        ws_path.mkdir()

        with patch("owrap.staging.get_workspace_config", return_value=fixed_config), \
             patch("owrap.staging.CONFIGS_DIR", fake_configs), \
             patch("owrap.staging.staged_dir", return_value=tmp_path / "staged"):
            out_dir = stage_all("marl")

        memory_page = out_dir / "self" / "memory.md"
        project_page = out_dir / "self" / "project.md"
        assert memory_page.is_file()
        assert project_page.is_file()
        assert "kind: project" in project_page.read_text()
        assert "{{RESEARCH_ROOT}}" not in project_page.read_text()
        self_text = (out_dir / "self.md").read_text()
        assert "[Memory](self/memory.md)" in self_text
        assert "## Command Reference" in self_text
        assert "## Agent Invocation Modes" not in self_text
        docs_root = tmp_path / "docs" / "research"
        assert not (docs_root / "self.md").exists()
        assert not (docs_root / "self").exists()
        assert (docs_root / "instruction.md").read_text() == (
            "# Workspace Instructions\n\n"
            "## Planner\n\n"
            "## Executor\n\n"
            "## Self\n"
        )
        assert "`--start --project <id>" in (
            out_dir / "planner.md"
        ).read_text()
        assert "`owrap updr [subproject] [--ctx]`" in (
            out_dir / "self" / "commands.md"
        ).read_text()

        settings_path = out_dir / "claude" / "settings.json"
        assert settings_path.exists()
        data = json.loads(settings_path.read_text())
        assert "permissions" in data
        assert "Grep" in data["permissions"]["allow"]
        assert "Read" in data["permissions"]["allow"]
        assert data["hooks"]["PreToolUse"][0]["matcher"] == (
            "Bash|Write|Edit"
        )
        assert data["hooks"]["PreToolUse"][0]["hooks"][0]["command"] == (
            "~/bin/owrap p"
        )

        permit_path = fake_configs / "marl_permit.json"
        assert permit_path.exists()
        permit_data = json.loads(permit_path.read_text())
        assert "Bash(cd *)" in permit_data["rules"]
        codex_permit = json.loads(
            (fake_configs / "marl_codex_permit.json").read_text()
        )
        assert "Bash(cd *)" in codex_permit["rules"]
        assert "Read" not in codex_permit["rules"]

        codex_hooks = json.loads((out_dir / "codex" / "hooks.json").read_text())
        groups = codex_hooks["hooks"]["PreToolUse"]
        assert len(groups) == 1
        assert groups[0]["matcher"] == "^Bash$"
        assert groups[0]["hooks"][0]["command"] == (
            "~/bin/owrap p --workspace marl"
        )
        approval_groups = codex_hooks["hooks"]["PermissionRequest"]
        assert len(approval_groups) == 1
        assert approval_groups[0]["matcher"] == "^Bash$"
        assert approval_groups[0]["hooks"][0]["command"] == (
            "~/bin/owrap p --workspace marl"
        )
        compact_groups = codex_hooks["hooks"]["PreCompact"]
        assert compact_groups[0]["matcher"] == "auto|manual"
        assert compact_groups[0]["hooks"][0]["command"] == (
            "~/bin/owrap ctx-hook"
        )

        claude_path = ws_path / "CLAUDE.md"
        assert claude_path.exists()
        content = claude_path.read_text()

        assert "## Allowed" in content
        assert "## Runner Tooling" in content

    def test_role_files_can_share_destination_and_change_without_user_loss(
        self, tmp_path,
    ):
        from owrap.staging import stage_all

        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / "CLAUDE.md").write_text("User Claude notes\n")
        (workspace / "AGENTS.md").write_text("User agent notes\n")
        config = {
            "workspace": str(workspace),
            "research_root": str(tmp_path / "records"),
            "bin_dir": str(tmp_path / "bin"),
            "role_harnesses": {
                "planner": ["codex", "claude"],
                "executor": ["claude"],
            },
        }
        configs = tmp_path / "configs"
        configs.mkdir()
        with patch("owrap.staging.get_workspace_config", return_value=config), \
             patch("owrap.staging.CONFIGS_DIR", configs), \
             patch("owrap.staging.staged_dir", return_value=tmp_path / "staged"):
            staged = stage_all("workspace")
            assert (staged / "planner.md").is_file()
            assert (staged / "executor.md").is_file()
            assert (staged / "self.md").is_file()
            assert (staged / "self" / "sessions.md").is_file()
            hooks = json.loads((staged / "codex" / "hooks.json").read_text())
            permit = hooks["hooks"]["PreToolUse"][0]["hooks"][0]
            assert permit["command"] == (
                f"{tmp_path / 'bin' / 'owrap'} p --workspace workspace"
            )
            assert (workspace / "AGENTS.md").read_text().count(
                "<!-- owrap:planner -->"
            ) == 1
            claude = (workspace / "CLAUDE.md").read_text()
            assert "<!-- owrap:planner -->" in claude
            assert "<!-- owrap:executor -->" in claude
            assert f"Read `{workspace / 'AGENTS.md'}`" in claude
            assert "User Claude notes" in claude

            config["role_harnesses"] = {
                "planner": ["codex"],
                "executor": ["opencode"],
            }
            stage_all("workspace")

        claude = (workspace / "CLAUDE.md").read_text()
        agents = (workspace / "AGENTS.md").read_text()
        assert claude == ""
        assert "<!-- owrap:planner -->" in agents
        assert "<!-- owrap:executor -->" in agents
        assert "User Claude notes" in agents
        assert "User agent notes" in agents

    def test_instruction_sections_are_staged_into_their_documents(
        self, tmp_path,
    ):
        from owrap.staging import stage_all

        workspace = tmp_path / "workspace"
        docs_root = tmp_path / "records"
        workspace.mkdir()
        docs_root.mkdir()
        (docs_root / "instruction.md").write_text(
            "# Workspace Instructions\n\n"
            "## Planner\n\nPlanner rule.\n\n"
            "## Executor\n\nExecutor rule.\n\n"
            "## Self\n\nShared reference.\n"
        )
        config = {
            "workspace": str(workspace),
            "docs_root": str(docs_root),
            "bin_dir": str(tmp_path / "bin"),
        }
        configs = tmp_path / "configs"
        configs.mkdir()
        with patch("owrap.staging.get_workspace_config", return_value=config), \
             patch("owrap.staging.CONFIGS_DIR", configs), \
             patch("owrap.staging.staged_dir", return_value=tmp_path / "staged"):
            staged = stage_all("workspace")

        planner = (staged / "planner.md").read_text()
        executor = (staged / "executor.md").read_text()
        self_text = (staged / "self.md").read_text()
        assert "Planner rule." in planner
        assert "Executor rule." not in planner
        assert "Executor rule." in executor
        assert "Planner rule." not in executor
        assert "Shared reference." in self_text
        assert "Planner rule." not in self_text

    def test_legacy_user_sections_migrate_once(self, tmp_path):
        from owrap.staging import stage_all

        workspace = tmp_path / "workspace"
        docs_root = tmp_path / "records"
        workspace.mkdir()
        docs_root.mkdir()
        (workspace / "CLAUDE.md").write_text(
            "<!-- owrap:planner -->\nGenerated\n<!-- /owrap:planner -->\n"
            "Planner note.\n"
        )
        (workspace / "AGENTS.md").write_text("Executor note.\n")
        (docs_root / "self.md").write_text(
            "<!-- owrap:self -->\nGenerated\n<!-- /owrap:self -->\n"
            "Self note.\n"
        )
        config = {
            "workspace": str(workspace),
            "docs_root": str(docs_root),
            "bin_dir": str(tmp_path / "bin"),
        }
        configs = tmp_path / "configs"
        configs.mkdir()
        with patch("owrap.staging.get_workspace_config", return_value=config), \
             patch("owrap.staging.CONFIGS_DIR", configs), \
             patch("owrap.staging.staged_dir", return_value=tmp_path / "staged"):
            stage_all("workspace")
            stage_all("workspace")

        instruction = (docs_root / "instruction.md").read_text()
        assert instruction.count("Planner note.") == 1
        assert instruction.count("Executor note.") == 1
        assert instruction.count("Self note.") == 1
        assert not (docs_root / "self.md").exists()

    def test_legacy_migration_preserves_other_instruction_sections(
        self, tmp_path,
    ):
        from owrap.staging import stage_all

        workspace = tmp_path / "workspace"
        docs_root = tmp_path / "records"
        workspace.mkdir()
        docs_root.mkdir()
        (workspace / "CLAUDE.md").write_text("Migrated planner rule.\n")
        (docs_root / "instruction.md").write_text(
            "# Local Instructions\n\n"
            "## Planner\n\nExisting planner rule.\n\n"
            "## Extra\n\nKeep this section.\n\n"
            "## Executor\n\nExisting executor rule.\n\n"
            "## Self\n"
        )
        config = {
            "workspace": str(workspace),
            "docs_root": str(docs_root),
            "bin_dir": str(tmp_path / "bin"),
        }
        configs = tmp_path / "configs"
        configs.mkdir()
        with patch("owrap.staging.get_workspace_config", return_value=config), \
             patch("owrap.staging.CONFIGS_DIR", configs), \
             patch("owrap.staging.staged_dir", return_value=tmp_path / "staged"):
            stage_all("workspace")

        instruction = (docs_root / "instruction.md").read_text()
        assert "Existing planner rule." in instruction
        assert "Migrated planner rule." in instruction
        assert "## Extra\n\nKeep this section." in instruction
        assert "Existing executor rule." in instruction
